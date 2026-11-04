"""HU-09 operativa: cálculos exactos, referencias previas y acceso privado."""
from datetime import UTC, date, datetime, timedelta
from contextlib import nullcontext
from decimal import Decimal
from unittest.mock import patch
from types import SimpleNamespace
import os
import unittest

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.analytics.forecast import day_forecast
from app.analytics.operational import DeliverySample, detect_alerts, robust_reference, operational_dashboard
from app.api.orders import router as orders_router
from app.api.logistics import router as logistics_router
from app.db.models import Entrega, HistorialPedido, Insumo, Pedido, Usuario, PrediccionDemanda, Alerta
from tests import test_analytics, test_orders_postgresql
from tests.test_logistics import add_order
from tests.auth_support import HEADERS

DAY = date(2026, 10, 26)


def delivery(db, when, duration=30, courier=1, *, complete=True):
    start = datetime.combine(when, datetime.min.time(), UTC) + timedelta(hours=12)
    order = add_order(db, estado='Entregado', fecha_hora=start - timedelta(minutes=20))
    row = Entrega(id_entrega=(db.scalar(select(func.max(Entrega.id_entrega))) or 0) + 1,
                  id_pedido=order.id_pedido, id_repartidor=courier, fecha_asignacion=start - timedelta(minutes=5),
                  estado='Entregado', costo_repartidor=0)
    db.add(row); db.flush()
    if complete:
        db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=1, tipo_evento='entrega', estado='En camino', fecha_hora=start))
    db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=1, tipo_evento='entrega', estado='Entregado', fecha_hora=start + timedelta(minutes=duration)))
    return row


class RulesTests(unittest.TestCase):
    def test_robust_reference_resists_extreme_and_avoids_minor_deviations(self):
        ref = robust_reference([Decimal(100)] * 20 + [Decimal(100000)], 20)
        self.assertEqual(ref, (100, Decimal(175)))
        self.assertIsNone(robust_reference([Decimal(100)] * 19, 20))
        stamp = datetime(2026, 10, 25, 12, tzinfo=UTC)
        orders = [SimpleNamespace(id_pedido=i, fecha_hora=stamp, estado='Entregado', importe_total=Decimal(100)) for i in range(20)]
        orders += [SimpleNamespace(id_pedido=100, fecha_hora=stamp + timedelta(days=1), estado='Nuevo', importe_total=Decimal(175)),
                   SimpleNamespace(id_pedido=101, fecha_hora=stamp + timedelta(days=1), estado='Nuevo', importe_total=Decimal(176))]
        self.assertEqual(set(detect_alerts(orders, [])[0]), {101})

    def test_same_day_and_future_amounts_do_not_define_reference(self):
        stamp = datetime(2026, 10, 25, 12, tzinfo=UTC)
        orders = [SimpleNamespace(id_pedido=i, fecha_hora=stamp, estado='Entregado', importe_total=Decimal(100)) for i in range(20)]
        orders.append(SimpleNamespace(id_pedido=100, fecha_hora=stamp, estado='Nuevo', importe_total=Decimal(99999)))
        self.assertEqual(detect_alerts(orders, [])[0], {})

    def test_courier_minimum_and_only_prior_completions_before_departure(self):
        stamp = datetime(2026, 10, 25, 12, tzinfo=UTC)
        prior = [DeliverySample(i, i, 1, stamp - timedelta(days=i+1, minutes=30), stamp - timedelta(days=i+1), Decimal(30)) for i in range(10)]
        current = DeliverySample(50, 50, 1, stamp, stamp + timedelta(minutes=58), Decimal(58))
        self.assertIn(50, detect_alerts([], sorted(prior + [current], key=lambda r:r.ended))[1])
        self.assertNotIn(50, detect_alerts([], sorted(prior[:9] + [current], key=lambda r:r.ended))[1])
        own = DeliverySample(51, 51, 3, stamp, stamp + timedelta(minutes=58), Decimal(58))
        self.assertNotIn(51, detect_alerts([], sorted(prior + [own], key=lambda r:r.ended))[1])
        overlapping = DeliverySample(52, 52, 1, stamp - timedelta(minutes=15), stamp + timedelta(minutes=15), Decimal(30))
        self.assertNotIn(50, detect_alerts([], sorted(prior[:9] + [overlapping, current], key=lambda r:r.ended))[1])


class OperationalTests(unittest.TestCase):
    setUp = test_analytics.ForecastTests.setUp
    sign_in = test_analytics.ForecastTests.sign_in

    def configure_client(self):
        test_analytics.ForecastTests.configure_client(self)
        self.app.include_router(orders_router, prefix='/api')
        self.app.include_router(logistics_router, prefix='/api')

    def history(self):
        with Session(self.engine) as db:
            return test_analytics.historical_orders(db, days=42, count=84)

    def test_targeted_warnings_equal_full_history_with_boundaries_and_couriers(self):
        from app.analytics.operational import owner_order_warnings
        self.history()
        with Session(self.engine) as db:
            for days in (110, 91, 90, 89, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1):
                delivery(db, DAY - timedelta(days=days), duration=30)
            delivery(db, DAY, duration=180)
            delivery(db, DAY, duration=45, courier=3)
            # Un viaje largo no se puede truncar a los eventos de los últimos 90 días.
            delivery(db, DAY - timedelta(days=100), duration=100 * 24 * 60)
            db.commit()
            owner = db.get(Usuario, 7)
            expected = owner_order_warnings(db, owner, None, reference_day=DAY)
            orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == 1)
                                .order_by(Pedido.fecha_hora, Pedido.id_pedido)).all()
            for targets in (orders[:3], orders[-6:], orders[30:40], orders[::9]):
                ids = [o.id_pedido for o in targets]
                for supplied in (None, targets):
                    actual = owner_order_warnings(db, owner, ids, reference_day=DAY, target_orders=supplied)
                    self.assertEqual(actual, {oid: expected[oid] for oid in ids})
            self.assertEqual(owner_order_warnings(db, db.get(Usuario, 1), [1]), {})
            self.assertEqual(owner_order_warnings(db, owner, [2, 999999], reference_day=DAY),
                             {oid: {'advertencia_importe': None, 'advertencia_entrega': None} for oid in (2, 999999)})

    def dashboard(self, day=None):
        return self.client.get('/api/restaurantes/1/indicadores' + (f'?fecha={day}' if day else ''))

    def test_exact_day_sales_ticket_top_products_seven_days_and_timezone(self):
        ids = self.history()
        with Session(self.engine) as db:
            db.get(Pedido, ids[-1]).estado = 'Cancelado'
            db.get(Pedido, ids[41]).fecha_hora = datetime(2026, 10, 27, 2, 59, 59, tzinfo=UTC)
            db.commit()
        response = self.dashboard()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['fecha'], str(DAY))
        self.assertEqual(data['pedidos'], 2)
        self.assertEqual(data['pedidos_entregados'], 1)
        self.assertEqual(Decimal(data['ventas']), 100)
        self.assertEqual(Decimal(data['ticket_promedio']), 100)
        self.assertEqual(data['productos'][0]['cantidad'], 14)
        self.assertEqual(len(data['evolucion']), 7)
        self.assertEqual(sum(Decimal(r['ventas']) for r in data['evolucion']), 1300)
        self.assertIsNone(data['entrega_minutos'])
        previous = self.dashboard('2026-10-25').json()
        self.assertEqual(previous['fecha'], '2026-10-25')
        self.assertEqual(Decimal(previous['ventas']), 200)
        self.assertEqual(self.dashboard('2026-10-27').status_code, 422)
        self.assertEqual(self.dashboard('2020-01-01').status_code, 422)

    def test_high_amount_badges_values_and_preserved_order_states(self):
        ids = self.history()
        with Session(self.engine) as db:
            db.get(Pedido, ids[0]).importe_total = 100000
            db.get(Pedido, ids[-1]).importe_total = 10000
            db.commit()
        response = self.dashboard()
        alerts = [r for r in response.json()['alertas'] if r['tipo'] == 'importe']
        self.assertEqual(len(alerts), 1)
        self.assertEqual(Decimal(alerts[0]['habitual']), 100)
        self.assertIn('$ 10.000,00', alerts[0]['mensaje'])
        self.assertIn('$ 100,00', alerts[0]['mensaje'])
        for period in ('dia', 'historial'):
            rows = self.client.get(f'/api/pedidos?periodo={period}').json()['pedidos']
            flagged = next(r for r in rows if r['id_pedido'] == ids[-1])
            self.assertEqual(flagged['advertencia_importe'], alerts[0]['mensaje'])
            self.assertEqual(flagged['estado'], 'Entregado')
        detail = self.client.get(f'/api/pedidos/{ids[-1]}').json()
        self.assertEqual(detail['advertencia_importe'], alerts[0]['mensaje'])
        with Session(self.engine) as db:
            db.get(Insumo, 1).stock_actual = Decimal(30)
            db.commit()
        with patch('app.orders.service.lock_order_relations') if self.engine.dialect.name == 'sqlite' else nullcontext():
            created = self.client.post('/api/restaurantes/1/pedidos', headers=HEADERS, json={
                'correo_cliente': 'u3@test.invalid', 'direccion_entrega': 'Fixture', 'medio_pago': 'efectivo', 'distancia_km': '2',
                'detalles': [{'id_producto': 1, 'cantidad': 100}]})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['estado'], 'Nuevo')
        with patch('app.logistics.priority.lock_order_relations') if self.engine.dialect.name == 'sqlite' else nullcontext():
            priority = self.client.post('/api/restaurantes/1/prioridades', headers=HEADERS)
        self.assertEqual(priority.status_code, 200, priority.text)
        priority_row = next(r for r in priority.json()['pedidos'] if r['id_pedido'] == created.json()['id_pedido'])
        self.assertIn('$ 10.000,00', priority_row['advertencia_importe'])
        self.sign_in(1)
        staff = self.client.get('/api/pedidos?periodo=dia').json()['pedidos']
        self.assertTrue(all(r['advertencia_importe'] is None for r in staff))

    def test_delivery_delays_use_own_history_and_ignore_missing_events(self):
        self.history()
        with Session(self.engine) as db:
            for i in range(10):
                delivery(db, DAY - timedelta(days=i+1), 30, 1)
                delivery(db, DAY - timedelta(days=i+1), 60, 3)
            late = delivery(db, DAY, 58, 1)
            normal = delivery(db, DAY, 58, 3)
            incomplete = delivery(db, DAY, 100, 1, complete=False)
            late_id, normal_id, incomplete_id = late.id_pedido, normal.id_pedido, incomplete.id_pedido
            db.commit()
        data = self.dashboard().json()
        self.assertEqual(data['entregas_con_tiempo'], 2)
        self.assertEqual(Decimal(data['entrega_minutos']), 58)
        self.assertEqual(data['entregas_habituales'], 1)
        self.assertEqual(data['entregas_demoradas'], 1)
        alert = next(r for r in data['alertas'] if r['tipo'] == 'entrega')
        self.assertEqual(alert['id_pedido'], late_id)
        self.assertIn('58 minutos', alert['mensaje'])
        self.assertIn('30 minutos', alert['mensaje'])
        rows = self.client.get('/api/pedidos?periodo=dia').json()['pedidos']
        by_id = {r['id_pedido']: r for r in rows}
        self.assertEqual(by_id[late_id]['advertencia_entrega'], alert['mensaje'])
        self.assertIsNone(by_id[normal_id]['advertencia_entrega'])
        self.assertIsNone(by_id[incomplete_id]['advertencia_entrega'])
        tracking = self.client.get(f'/api/pedidos/{late_id}/seguimiento')
        self.assertEqual(tracking.status_code, 200, tracking.text)
        self.assertEqual(tracking.json()['entrega']['advertencia_entrega'], alert['mensaje'])
        self.assertEqual(tracking.json()['entrega']['estado'], 'Entregado')

    def test_forecast_stock_is_reused_exactly_without_writes(self):
        self.history()
        with Session(self.engine) as db:
            db.get(Insumo, 1).stock_actual = 1
            db.commit()
            expected = day_forecast(db, 1, DAY)
        with patch('app.analytics.forecast.day_forecast', wraps=day_forecast) as forecast:
            data = self.dashboard().json()
        self.assertEqual(forecast.call_count, 1)
        stock = [r for r in data['alertas'] if r['tipo'] == 'stock']
        self.assertEqual(len(stock), 1)
        self.assertEqual(Decimal(stock[0]['observado']), expected.insumos[0].faltante)
        self.assertEqual(stock[0]['fecha_pronostico'], str(DAY))
        historical = self.dashboard('2026-10-25').json()
        self.assertEqual(historical['fecha_stock'], str(DAY))
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(PrediccionDemanda)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Alerta)), 0)

    def test_access_owner_only_and_tenant_isolation(self):
        self.history()
        self.assertEqual(self.client.get('/api/restaurantes/2/indicadores').status_code, 403)
        with Session(self.engine) as db:
            db.get(Pedido, 2).estado = 'Entregado'
            db.get(Pedido, 2).importe_total = 999999
            db.commit()
        self.assertEqual(Decimal(self.dashboard().json()['ventas']), 200)
        for uid in (1, 3, 5):
            self.sign_in(uid)
            self.assertEqual(self.dashboard().status_code, 403)
            self.assertEqual(self.client.get('/api/restaurantes/1/alertas').status_code, 403)

    def test_empty_and_insufficient_are_explicit_and_alerts_are_limited(self):
        data = self.dashboard().json()
        self.assertEqual(data['ventas'], '0')
        self.assertEqual(data['alertas'], [])
        self.assertIsNone(data['ticket_promedio'])
        self.assertIsNone(data['entrega_minutos'])
        self.assertIsNotNone(data['aviso_stock'])
        ids = self.history()
        with Session(self.engine) as db:
            for i in range(8):
                add_order(db, estado='Nuevo', fecha_hora=datetime(2026, 10, 26, 12+i, tzinfo=UTC), importe_total=10000)
            db.commit()
        data = self.dashboard().json()
        self.assertEqual(data['total_alertas'], 8)
        self.assertEqual(len(data['alertas']), 6)


@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Requiere PostgreSQL local descartable')
class OperationalPostgreSQLTests(OperationalTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables
