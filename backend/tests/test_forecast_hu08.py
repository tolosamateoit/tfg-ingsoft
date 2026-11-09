"""Casos exactos de HU-08, sin acceso a Supabase."""
import unittest
from datetime import date, datetime, UTC, timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.forecast import calculate_forecast, evaluate_series, ingredient_needs, associations, generate_forecast, latest_forecast
from app.analytics.schemas import ForecastItem
from app.db.models import Pedido, DetallePedido, Producto, RecetaDetalle, Insumo
from tests.menu_support import sqlite_menu_engine
from tests.test_analytics import historical_orders


class TemporalTests(unittest.TestCase):
    def test_weekday_selection_exact_mae_and_future_week(self):
        start = date(2026, 9, 21)
        values = [i % 7 + 1 for i in range(35)]
        method, scores, errors, daily = evaluate_series(values, start)
        self.assertEqual(method, 'promedio_dia_semana')
        self.assertEqual(scores[method], 0)
        self.assertEqual(errors[method], 0)
        self.assertAlmostEqual(scores['promedio_diario'], 12 / 7)
        self.assertEqual(daily, [Decimal(i) for i in range(1, 8)])

    def test_holdout_cannot_choose_method_and_mae_is_exact(self):
        values = [i % 7 + 1 for i in range(35)]
        values[-7:] = [100] * 7
        method, scores, errors, _ = evaluate_series(values, date(2026, 9, 21))
        self.assertEqual(method, 'promedio_dia_semana')
        self.assertEqual(scores[method], 0)
        self.assertEqual(errors[method], 96)
        self.assertEqual(evaluate_series(values, date(2026, 9, 21)), evaluate_series(values, date(2026, 9, 21)))

    def test_simple_reference_wins_tie_and_insufficient_history(self):
        self.assertEqual(evaluate_series([5] * 35, date(2026, 9, 21))[0], 'promedio_diario')
        with self.assertRaises(ValueError):
            evaluate_series([5] * 34, date(2026, 9, 21))

    def test_associations_require_evidence_not_popularity(self):
        names = {1: 'Lomito', 2: 'Bebida'}
        self.assertEqual(associations({i: {1, 2} for i in range(100)}, names), [])
        self.assertEqual(associations({i: {1, 2} for i in range(9)}, names), [])
        baskets = {i: ({1, 2} if i < 30 else set()) for i in range(100)}
        messages = associations(baskets, names)
        self.assertEqual(len(messages), 2)
        self.assertIn('30 de 30', messages[0])
        self.assertIn('3.33', messages[0])


class CalculationTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.ids = historical_orders(self.db)

    def test_states_zero_days_quantities_future_and_tenant(self):
        # Entire first weekday is cancelled: zeros must remain on calendar.
        for index in (0, 35):
            self.db.get(Pedido, self.ids[index]).estado = 'Cancelado'
        # Another tenant with huge valid quantity must not affect restaurant 1.
        other = self.db.get(Pedido, 2)
        other.estado = 'Entregado'
        self.db.scalar(select(DetallePedido).where(DetallePedido.id_pedido == 2)).cantidad = 99999
        # Future valid order is explicitly excluded at the operational cutoff.
        future = Pedido(id_restaurante=1, id_cliente=1, fecha_hora=datetime(2026, 11, 1, 12, tzinfo=UTC),
            estado='Entregado', direccion_entrega='Fixture', medio_pago='efectivo', estado_pago='pendiente',
            importe_total=100, costo_total=10, distancia_km=1)
        self.db.add(future); self.db.flush()
        self.db.add(DetallePedido(id_pedido=future.id_pedido, id_producto=1, cantidad=99999, precio_unitario=100))
        self.db.commit()
        with patch('app.analytics.forecast.analysis_reference_date', return_value=date(2026, 10, 26)):
            result = calculate_forecast(self.db, 1)
        self.assertEqual(result.dias_historial, 35)  # las fechas con pedidos cancelados también son operativas
        self.assertEqual(result.pedidos_completados, 68)
        # Restore first day; cancel an interior day instead.
        for index in (0, 35):
            self.db.get(Pedido, self.ids[index]).estado = 'Entregado'
        for index in (7, 42):
            self.db.get(Pedido, self.ids[index]).estado = 'Cancelado'
        self.db.commit()
        with patch('app.analytics.forecast.analysis_reference_date', return_value=date(2026, 10, 26)):
            result = calculate_forecast(self.db, 1)
        self.assertEqual(result.pedidos_completados, 68)
        self.assertEqual(result.dias_historial, 35)
        p = result.predicciones[0]
        self.assertEqual(p.periodo_inicio, date(2026, 10, 27))
        self.assertEqual(p.periodo_fin, date(2026, 11, 2))
        self.assertGreater(p.demanda_estimada, 0)
        self.assertGreaterEqual(p.valor_metrica, 0)
        self.assertEqual(len(p.dias), 7)
        self.assertIn('incluidos días operativos sin pedidos', p.explicacion)

    def test_local_midnight_boundary(self):
        last = self.db.get(Pedido, self.ids[-1])
        last.fecha_hora = datetime(2026, 10, 27, 2, 59, 59, tzinfo=UTC)
        self.db.commit()
        result = calculate_forecast(self.db, 1)
        self.assertEqual(result.fecha_operativa, date(2026, 10, 26))
        self.assertEqual(result.predicciones[0].demanda_estimada, Decimal('112.2'))

    def test_shared_recipes_beverages_rounding_stock_and_saved_metadata(self):
        self.db.add(Producto(id_producto=3, id_restaurante=1, nombre='Bebida', precio=1, costo_unitario=1, activo=True))
        self.db.add(Insumo(id_insumo=4, id_restaurante=1, nombre='Botella', unidad='unidad', stock_actual=1, costo_unitario=1))
        self.db.flush()
        self.db.add_all([RecetaDetalle(id_producto=1, id_insumo=1, cantidad=Decimal('.2'), unidad='kg'),
            RecetaDetalle(id_producto=3, id_insumo=1, cantidad=Decimal('.1'), unidad='kg'),
            RecetaDetalle(id_producto=3, id_insumo=4, cantidad=1, unidad='unidad')])
        self.db.commit()
        with patch('app.analytics.forecast.lock_order_relations'):
            generated = generate_forecast(self.db, 1)
        saved = latest_forecast(self.db, 1)
        self.assertEqual(saved.predicciones, generated.predicciones)
        self.assertEqual(saved.mae, generated.mae)
        original = generated.predicciones[0]
        beverage = original.model_copy(update={'id_producto': 3, 'producto': 'Bebida', 'demanda_estimada': Decimal('2.5')})
        needs, missing = ingredient_needs(self.db, 1, [original, beverage])
        by_id = {r.id_insumo: r for r in needs}
        self.assertEqual(missing, [])
        self.assertEqual(by_id[1].cantidad_necesaria, Decimal('22.69'))
        self.assertEqual(by_id[4].faltante, Decimal('1.5'))
        self.assertEqual(by_id[4].reposicion_sugerida, 2)
        self.assertEqual(self.db.get(Insumo, 4).stock_actual, 1)
        self.assertIn('reponer 2 unidad', by_id[4].explicacion)
        self.db.get(RecetaDetalle, (3, 4)).unidad = 'kg'
        self.db.flush()
        with self.assertRaises(HTTPException):
            ingredient_needs(self.db, 1, [beverage])

    def test_invalid_cross_tenant_ingredient_rejected(self):
        self.db.add(RecetaDetalle(id_producto=1, id_insumo=3, cantidad=1, unidad='kg'))
        self.db.commit()
        with self.assertRaises(HTTPException):
            calculate_forecast(self.db, 1)
