"""Previsión diaria: fechas operativas, unidades de preparación y lectura segura."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
import unittest

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.forecast import day_forecast
from app.db.models import DetallePedido, Insumo, Pedido, PrediccionDemanda, Producto, RecetaDetalle
from tests import test_analytics


class DayForecastTests(unittest.TestCase):
    setUp = test_analytics.ForecastTests.setUp
    configure_client = test_analytics.ForecastTests.configure_client
    sign_in = test_analytics.ForecastTests.sign_in

    def history(self):
        with Session(self.engine) as db:
            return test_analytics.historical_orders(db, days=42, count=84)

    def daily(self, value=None):
        suffix = f'?fecha={value}' if value is not None else ''
        return self.client.get(test_analytics.BASE + '/predicciones/diaria' + suffix)

    def test_exact_eight_dates_and_each_response_matches_selected_day(self):
        self.history()
        baseline = date(2026, 10, 26)
        options = self.daily().json()['fechas_disponibles']
        self.assertEqual([r['fecha'] for r in options], [(baseline + timedelta(days=i)).isoformat() for i in range(8)])
        self.assertEqual(options[0]['etiqueta'], 'Lun 26/10')
        self.assertEqual(options[-1]['etiqueta'], 'Lun 02/11')
        for i in range(8):
            target = baseline + timedelta(days=i)
            response = self.daily(target)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data['fecha_seleccionada'], target.isoformat())
            self.assertEqual(data['fecha_operativa'], baseline.isoformat())
            self.assertEqual(data['productos'][0]['cantidad'], ((i + 6) % 7 + 1) * 4)
            self.assertEqual(data['pedidos_estimados'], 2)
            self.assertEqual(data['evaluacion']['predicciones'][0]['dias'][0]['fecha'], target.isoformat())
            self.assertEqual(len(data['evaluacion']['predicciones'][0]['dias']), 1)
        for invalid in ('2026-10-25', '2026-11-03', 'invalid'):
            self.assertEqual(self.daily(invalid).status_code, 422)

    def test_current_target_sales_and_future_orders_never_leak(self):
        ids = self.history()
        before = self.daily().json()
        with Session(self.engine) as db:
            for order_id in (ids[41], ids[83]):
                detail = db.scalar(select(DetallePedido).where(DetallePedido.id_pedido == order_id))
                detail.cantidad = 99999
            # Fecha futura respecto del corte operativo fijado para esta comprobación.
            db.get(Pedido, ids[40]).fecha_hora += timedelta(days=20)
            db.commit()
        with patch('app.analytics.forecast.operational_date', return_value=date(2026, 10, 26)):
            after = self.daily().json()
        self.assertEqual(before['productos'], after['productos'])
        self.assertEqual(before['pedidos_estimados'], after['pedidos_estimados'])
        self.assertEqual(before['explicaciones'], after['explicaciones'])

    def test_integer_preparation_shared_recipes_beverages_and_purchase_units(self):
        ids = self.history()
        with Session(self.engine) as db:
            db.scalar(select(DetallePedido).where(DetallePedido.id_pedido == ids[6])).cantidad += 1
            db.get(Insumo, 1).stock_actual = 1
            db.add(Producto(id_producto=3, id_restaurante=1, nombre='Bebida', precio=1, costo_unitario=1, activo=True))
            db.add(Insumo(id_insumo=4, id_restaurante=1, nombre='Botella', unidad='unidad', stock_actual=Decimal('1.7'), costo_unitario=1))
            db.flush()
            for oid in ids:
                db.add(DetallePedido(id_pedido=oid, id_producto=3, cantidad=1, precio_unitario=1))
            db.add_all([RecetaDetalle(id_producto=3, id_insumo=1, cantidad=Decimal('.1'), unidad='kg'),
                        RecetaDetalle(id_producto=3, id_insumo=4, cantidad=1, unidad='unidad')])
            db.commit()
        data = self.daily().json()
        product = data['productos'][0]
        self.assertEqual(product['estimacion_original'], '28.200000')
        self.assertEqual(product['cantidad'], 29)
        self.assertTrue(all(isinstance(p['cantidad'], int) for p in data['productos']))
        needs = {r['id_insumo']: r for r in data['insumos']}
        self.assertEqual(Decimal(needs[1]['cantidad_necesaria']), 6)
        self.assertEqual(Decimal(needs[1]['reposicion_sugerida']), 5)
        self.assertEqual(Decimal(needs[4]['stock_actual']), 1)
        self.assertEqual(Decimal(needs[4]['reposicion_sugerida']), 1)
        self.assertEqual(data['cantidad_faltantes'], 2)
        self.assertIn('lunes anteriores', data['explicaciones'][0])
        self.assertIn(product['nombre'], data['explicaciones'][1])
        self.assertEqual(data['evaluacion']['predicciones'][0]['modelo'], 'promedio_dia_semana')
        self.assertIsNotNone(data['evaluacion']['mae'])
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 4).stock_actual, Decimal('1.7'))
            self.assertEqual(db.scalar(select(func.count()).select_from(PrediccionDemanda)), 0)

    def test_cancellations_zero_days_and_no_recipe_warning(self):
        ids = self.history()
        with Session(self.engine) as db:
            for oid in (ids[6], ids[48]):
                db.get(Pedido, oid).estado = 'Cancelado'
            db.delete(db.get(RecetaDetalle, (1, 1)))
            db.commit()
        data = self.daily().json()
        self.assertEqual(data['productos'][0]['estimacion_original'], '22.400000')
        self.assertEqual(data['productos'][0]['cantidad'], 23)
        self.assertEqual(data['pedidos_estimados'], 2)  # 1.6 redondeado hacia arriba
        self.assertFalse(data['compras_completas'])
        self.assertIn('faltan recetas', data['aviso'])
        self.assertEqual(data['insumos'], [])

    def test_insufficient_history_keeps_selector_without_inventing_estimates(self):
        with Session(self.engine) as db:
            test_analytics.historical_orders(db, days=7, count=10)
        data = self.daily().json()
        self.assertEqual(len(data['fechas_disponibles']), 8)
        self.assertEqual(data['productos'], [])
        self.assertIsNone(data['pedidos_estimados'])
        self.assertIn('suficiente historial', data['aviso'])

    def test_authorization_and_restaurant_scope(self):
        self.history()
        with Session(self.engine) as db:
            db.get(Pedido, 2).estado = 'Entregado'
            db.scalar(select(DetallePedido).where(DetallePedido.id_pedido == 2)).cantidad = 99999
            db.commit()
        self.assertEqual(self.daily().json()['productos'][0]['cantidad'], 28)
        self.assertEqual(self.client.get('/api/restaurantes/2/predicciones/diaria').status_code, 403)
        self.sign_in(1)
        self.assertEqual(self.daily().status_code, 403)
