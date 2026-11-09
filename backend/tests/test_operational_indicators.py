"""Días operativos, P95 y permanencias a partir de historiales reales."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
import os
import unittest
from sqlalchemy import literal
from sqlalchemy.orm import Session
from app.analytics.operational import operational_dashboard, percentile_95
from app.db.models import DetallePedido, DiaOperativo, HistorialPedido, Pedido, Restaurante, Usuario
from tests import test_operational_analytics as support, test_orders_postgresql
from tests.test_logistics import add_order

TARGET = date(2026, 11, 1)
NOW = datetime(2026, 11, 1, 18, tzinfo=UTC)

class IndicatorsTests(unittest.TestCase):
    setUp = support.OperationalTests.setUp
    configure_client = support.OperationalTests.configure_client
    sign_in = support.OperationalTests.sign_in

    def result(self, db, target=TARGET):
        with patch('app.analytics.operational.analysis_reference_date', return_value=TARGET), \
             patch('app.analytics.operational.func.now', return_value=literal(NOW)):
            return operational_dashboard(db, db.get(Usuario, 7), 1, target)

    def test_percentile_nearest_rank_and_minimum(self):
        self.assertIsNone(percentile_95([Decimal(1)] * 19))
        self.assertEqual(percentile_95([Decimal(i) for i in range(1, 21)]), 19)
        self.assertEqual(percentile_95([Decimal(10)] * 20), 10)

    def test_seven_operational_dates_skip_closed_and_show_zero(self):
        with Session(self.engine) as db:
            db.get(Restaurante, 1).abierto = False
            db.get(Pedido, 1).fecha_hora = datetime(2020, 1, 1, 12, tzinfo=UTC)
            dates = [TARGET - timedelta(days=3 * i) for i in reversed(range(9))]
            db.add_all([DiaOperativo(id_restaurante=1, fecha=day) for day in dates])
            sold = dates[-2]
            add_order(db, estado='Entregado', fecha_hora=datetime(sold.year, sold.month, sold.day, 12, tzinfo=UTC), importe_total=150)
            db.commit()
            result = self.result(db)
        self.assertEqual([row.fecha for row in result.evolucion], dates[-7:])
        self.assertEqual([row.ventas for row in result.evolucion], [0, 0, 0, 0, 0, 150, 0])

    def test_p95_uses_30_operational_days_and_excludes_closed_days_and_future_sales(self):
        with Session(self.engine) as db:
            db.get(Restaurante, 1).abierto = False
            db.get(Pedido, 1).estado = 'Cancelado'
            db.get(Pedido, 1).fecha_hora = datetime(2020, 1, 1, 12, tzinfo=UTC)
            for offset in range(1, 32):
                day = TARGET - timedelta(days=offset * 2)
                db.add(DiaOperativo(id_restaurante=1, fecha=day))
                if offset <= 20:
                    add_order(db, estado='Entregado', fecha_hora=datetime(day.year, day.month, day.day, 12, tzinfo=UTC), importe_total=offset)
                if offset == 31:
                    add_order(db, estado='Entregado', fecha_hora=datetime(day.year, day.month, day.day, 12, tzinfo=UTC), importe_total=999999)
            moment = datetime(2026, 11, 1, 12, tzinfo=UTC)
            foreign = Pedido(id_restaurante=2, id_cliente=2, fecha_hora=moment - timedelta(days=2),
                estado='Entregado', direccion_entrega='Prueba', medio_pago='efectivo', estado_pago='pagado',
                importe_total=999999, costo_total=10, distancia_km=1)
            db.add(foreign); db.flush()
            db.add(DetallePedido(id_pedido=foreign.id_pedido, id_producto=2, cantidad=1, precio_unitario=100))
            same = add_order(db, estado='Nuevo', fecha_hora=moment, importe_total=19)
            high = add_order(db, estado='Nuevo', fecha_hora=moment, importe_total=20)
            cancel = add_order(db, estado='Cancelado', fecha_hora=moment, importe_total=999999)
            high_id, same_id, cancel_id = high.id_pedido, same.id_pedido, cancel.id_pedido
            db.commit()
            result = self.result(db)
            alerts = [a for a in result.alertas if a.tipo == 'importe']
            self.assertEqual(sorted(a.id_pedido for a in alerts), sorted([high_id, cancel_id]))
            self.assertEqual(alerts[0].umbral, 19)
            self.assertNotIn(same_id, [a.id_pedido for a in alerts])
            self.assertIn(cancel_id, [a.id_pedido for a in alerts])
            baseline = db.query(Pedido).filter(Pedido.id_restaurante == 1, Pedido.estado == 'Entregado', Pedido.importe_total == 1).one()
            baseline.estado = 'Cancelado'; db.commit()
            self.assertFalse(any(a.tipo == 'importe' for a in self.result(db).alertas))

    def test_completed_and_current_delays_are_grouped_and_averages_ignore_open_states(self):
        with Session(self.engine) as db:
            db.get(Restaurante, 1).abierto = False
            db.get(Pedido, 1).fecha_hora = datetime(2020, 1, 1, 12, tzinfo=UTC)
            before = TARGET - timedelta(days=2)
            db.add(DiaOperativo(id_restaurante=1, fecha=before))
            previous = add_order(db, estado='Entregado', fecha_hora=datetime(before.year, before.month, before.day, 12, tzinfo=UTC))
            current = add_order(db, estado='Listo', fecha_hora=datetime(2026, 11, 1, 17, 0, tzinfo=UTC))
            incomplete = add_order(db, estado='Nuevo', fecha_hora=datetime(2026, 11, 1, 17, 5, tzinfo=UTC))
            base = datetime(before.year, before.month, before.day, 12, tzinfo=UTC)
            for oid, stamp, changes in ((previous.id_pedido, base, [('Nuevo', 0), ('En preparación', 10), ('Listo', 20), ('Entregado', 30)]),
                (current.id_pedido, datetime(2026, 11, 1, 17, 0, tzinfo=UTC), [('Nuevo', 0), ('En preparación', 16), ('Listo', 32)])):
                for state, minute in changes:
                    db.add(HistorialPedido(id_pedido=oid, id_usuario=1, tipo_evento='estado', estado=state, fecha_hora=stamp + timedelta(minutes=minute)))
            # Un cambio de distancia no reinicia la permanencia.
            db.add(HistorialPedido(id_pedido=current.id_pedido, id_usuario=1, tipo_evento='distancia', estado='En preparación', fecha_hora=datetime(2026, 11, 1, 17, 20, tzinfo=UTC)))
            db.add(HistorialPedido(id_pedido=incomplete.id_pedido, id_usuario=1, tipo_evento='registro', estado='Nuevo', fecha_hora=datetime(2026, 11, 1, 17, 5, tzinfo=UTC)))
            db.commit()
            result = self.result(db)
            averages = {row.estado: row.minutos for row in result.tiempos_promedio}
            self.assertEqual(averages['Nuevo'], 16)
            self.assertEqual(averages['En preparación'], 16)
            self.assertIsNone(averages['Listo'])
            self.assertNotIn('Entregado', averages)
            alerts = [a for a in result.alertas if a.tipo == 'demora' and a.id_pedido == current.id_pedido]
            self.assertEqual(len(alerts), 1)
            self.assertEqual([(d.estado, d.minutos, d.habitual) for d in alerts[0].demoras],
                             [('Nuevo', 16, 10), ('En preparación', 16, 10), ('Listo', 28, 10)])
            self.assertTrue(any(a.tipo == 'demora' and a.id_pedido == incomplete.id_pedido for a in result.alertas))
            self.assertEqual(db.get(Pedido, current.id_pedido).estado, 'Listo')

    def test_strict_50_percent_and_no_alert_without_complete_reference(self):
        with Session(self.engine) as db:
            db.get(Restaurante, 1).abierto = False
            db.get(Pedido, 1).fecha_hora = datetime(2020, 1, 1, 12, tzinfo=UTC)
            previous_day = TARGET - timedelta(days=1)
            start = datetime(previous_day.year, previous_day.month, previous_day.day, 12, tzinfo=UTC)
            prior = add_order(db, estado='Entregado', fecha_hora=start)
            exactly = add_order(db, estado='Cancelado', fecha_hora=datetime(2026, 11, 1, 16, 0, tzinfo=UTC))
            just_over = add_order(db, estado='Cancelado', fecha_hora=datetime(2026, 11, 1, 16, 30, tzinfo=UTC))
            no_baseline = add_order(db, estado='En camino', fecha_hora=datetime(2026, 11, 1, 17, 0, tzinfo=UTC))
            for order, begin, end_state, seconds in (
                (prior, start, 'Entregado', 600), (exactly, datetime(2026, 11, 1, 16, 0, tzinfo=UTC), 'Cancelado', 900),
                (just_over, datetime(2026, 11, 1, 16, 30, tzinfo=UTC), 'Cancelado', 901)):
                db.add_all([HistorialPedido(id_pedido=order.id_pedido, id_usuario=1, tipo_evento='estado', estado='Nuevo', fecha_hora=begin),
                    HistorialPedido(id_pedido=order.id_pedido, id_usuario=1, tipo_evento='estado', estado=end_state, fecha_hora=begin + timedelta(seconds=seconds))])
            db.add(HistorialPedido(id_pedido=no_baseline.id_pedido, id_usuario=1, tipo_evento='entrega', estado='En camino',
                                   fecha_hora=datetime(2026, 11, 1, 17, 0, tzinfo=UTC)))
            db.commit()
            alerts = [a for a in self.result(db).alertas if a.tipo == 'demora']
            self.assertNotIn(exactly.id_pedido, [a.id_pedido for a in alerts])
            self.assertIn(just_over.id_pedido, [a.id_pedido for a in alerts])
            self.assertNotIn(no_baseline.id_pedido, [a.id_pedido for a in alerts])


@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Requiere PostgreSQL local descartable')
class IndicatorsPostgreSQLTests(IndicatorsTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables
