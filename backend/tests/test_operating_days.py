import unittest
from datetime import date, datetime, timedelta, UTC
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.analytics.forecast import calculate_forecast, evaluate_series, predict
from app.analytics.operational import operational_dashboard
from app.db.models import DetallePedido, DiaOperativo, Pedido, Restaurante, Usuario
from app.orders.operating_days import operating_days, register_open_days
from tests.menu_support import sqlite_menu_engine

class OperatingDaysTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.restaurant = self.db.get(Restaurante, 1)
        self.restaurant.abierto = False
        self.db.commit()

    def test_open_across_midnights_and_closed_gaps(self):
        first = date(2026, 11, 1)
        self.db.add(DiaOperativo(id_restaurante=1, fecha=first))
        self.restaurant.abierto = True
        self.db.commit()
        later = first + timedelta(days=3)
        self.assertEqual(operating_days(self.db, 1, first, later, today=later),
                         [first + timedelta(days=i) for i in range(4)])
        self.assertEqual(self.db.scalar(select(DiaOperativo.fecha).where(DiaOperativo.fecha == later)), None)
        register_open_days(self.db, self.restaurant, later)
        register_open_days(self.db, self.restaurant, later)
        self.restaurant.abierto = False
        self.db.commit()
        self.assertEqual(operating_days(self.db, 1, first, later + timedelta(days=3), today=later + timedelta(days=3)),
                         [first + timedelta(days=i) for i in range(4)])
        self.assertEqual(operating_days(self.db, 2, first, later, today=later), [])

    def test_historical_orders_define_days_even_when_cancelled(self):
        order = self.db.get(Pedido, 1)
        order.estado = 'Cancelado'
        self.db.commit()
        self.assertIn(date(2026, 10, 25), operating_days(self.db, 1, date(2026, 10, 25), date(2026, 10, 25)))

    def test_weekday_averages_use_actual_dates_and_operational_zero(self):
        first = date(2026, 9, 1)
        dates = [first + timedelta(days=i) for i in range(50) if i % 7 != 0]
        values = [0 if day.weekday() == 4 else 10 for day in dates]
        friday = next(day for day in dates if day.weekday() == 4)
        self.assertEqual(predict(values, first, 0, 'promedio_dia_semana', dates=dates, target=friday), 0)
        method, _, _, predictions = evaluate_series(values, first, dates=dates, future_start=friday)
        self.assertEqual(method, 'promedio_dia_semana')
        self.assertEqual(predictions[0], 0)

    def test_forecast_excludes_closed_days_but_keeps_open_day_without_orders(self):
        start = date(2026, 8, 1)
        days = [start + timedelta(days=i) for i in range(42) if i % 6 != 0]
        self.assertEqual(len(days), 35)
        zero = days[10]
        self.db.add(DiaOperativo(id_restaurante=1, fecha=zero))
        for day in days:
            if day == zero:
                continue
            order = Pedido(id_restaurante=1, id_cliente=1, fecha_hora=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
                estado='Entregado', direccion_entrega='Prueba', medio_pago='efectivo', estado_pago='pagado',
                importe_total=100, costo_total=10, distancia_km=1)
            self.db.add(order)
            self.db.flush()
            self.db.add(DetallePedido(id_pedido=order.id_pedido, id_producto=1, cantidad=10, precio_unitario=100))
        self.db.commit()
        reference = days[-1]
        first = calculate_forecast(self.db, 1, reference_day=reference)
        after_closure = calculate_forecast(self.db, 1, reference_day=reference + timedelta(days=7))
        self.assertEqual(first.dias_historial, 35)
        self.assertEqual(after_closure.dias_historial, 35)
        self.assertEqual(first.predicciones[0].demanda_estimada, after_closure.predicciones[0].demanda_estimada)
        self.assertLess(first.predicciones[0].demanda_estimada, 70)

    def test_zero_demand_only_alerts_on_operational_day(self):
        target = date(2026, 11, 1)
        for i in range(1, 22):
            day = target - timedelta(days=i)
            self.db.add(Pedido(id_restaurante=1, id_cliente=1, fecha_hora=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
                estado='Nuevo', direccion_entrega='Prueba', medio_pago='efectivo', estado_pago='pendiente',
                importe_total=100, costo_total=10, distancia_km=1))
        self.db.commit()
        user = self.db.get(Usuario, 7)
        with patch('app.analytics.operational.analysis_reference_date', return_value=target):
            closed = operational_dashboard(self.db, user, 1, target)
            self.db.add(DiaOperativo(id_restaurante=1, fecha=target))
            self.db.flush()
            opened = operational_dashboard(self.db, user, 1, target)
        self.assertFalse(any(alert.tipo == 'demanda' for alert in closed.alertas))
        self.assertTrue(any(alert.tipo == 'demanda' and alert.observado == 0 for alert in opened.alertas))
