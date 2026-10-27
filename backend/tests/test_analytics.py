"""Datos sintéticos exclusivamente en fixtures locales, nunca en Supabase."""

import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.db.models import Alerta, DetallePedido, HistorialPedido, Insumo, Pedido, PrediccionDemanda, RecetaDetalle
from app.main import validation_error
from tests.auth_support import HEADERS, PASSWORD, override_database
from tests.menu_support import sqlite_menu_engine
from tests.test_logistics import add_order

TODAY = date(2026, 10, 27)
BASE = "/api/restaurantes/1"


def historical_orders(db, *, days=7, count=10):
    start = datetime.combine(TODAY - timedelta(days=days), datetime.min.time(), UTC)
    rows = []
    for index in range(count):
        day = index % days
        copies = (count - 1 - day) // days + 1
        order = Pedido(id_restaurante=1, id_cliente=1, fecha_hora=start + timedelta(days=day, hours=12),
                       estado="Entregado", direccion_entrega="Fixture", medio_pago="efectivo", estado_pago="pendiente",
                       importe_total=100, costo_total=10, distancia_km=1)
        db.add(order); db.flush()
        db.add(DetallePedido(id_pedido=order.id_pedido, id_producto=1, precio_unitario=100,
                             cantidad=(day + 1) * 4 // copies))
        rows.append(order.id_pedido)
    db.commit()
    return rows


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        for target in ("app.auth.service.lock_email", "app.analytics.forecast.lock_order_relations", "app.analytics.metrics.lock_order_relations"):
            context = patch(target)
            context.start(); self.addCleanup(context.stop)
        self.configure_client()

    def configure_client(self):
        context = patch("app.analytics.forecast.utc_today", return_value=TODAY)
        context.start(); self.addCleanup(context.stop)
        context = patch("app.analytics.metrics.utc_today", return_value=TODAY)
        context.start(); self.addCleanup(context.stop)
        with Session(self.engine) as db:
            db.add(RecetaDetalle(id_producto=1, id_insumo=1, cantidad=Decimal("0.2"), unidad="kg"))
            db.commit()
        self.app = FastAPI()
        for router in (auth_router, analytics_router):
            self.app.include_router(router, prefix="/api")
        self.app.add_exception_handler(RequestValidationError, validation_error)
        override_database(self.app, self.engine)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.sign_in(7)

    def sign_in(self, user):
        self.client.cookies.clear()
        response = self.client.post("/api/auth/login", headers=HEADERS,
                                    json={"correo": f"u{user}@test.invalid", "contrasena": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)

    def generate(self):
        return self.client.post(BASE + "/predicciones", headers=HEADERS)

    def test_empty_history_does_not_generate_or_persist_predictions(self):
        response = self.generate()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["estado"], "Historial insuficiente")
        self.assertEqual(response.json()["predicciones"], [])
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(PrediccionDemanda)), 0)

    def test_seven_days_and_nine_orders_are_insufficient(self):
        with Session(self.engine) as db:
            historical_orders(db, count=9)
        response = self.generate()
        self.assertEqual(response.json()["estado"], "Historial insuficiente")
        self.assertEqual(response.json()["dias_historial"], 7)

    def test_six_days_and_ten_orders_are_insufficient(self):
        with Session(self.engine) as db:
            historical_orders(db, days=6)
        self.assertEqual(self.generate().json()["estado"], "Historial insuficiente")

    def test_linear_history_forecast_mae_recipes_shortages_and_persistence(self):
        with Session(self.engine) as db:
            historical_orders(db)
        response = self.generate()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["pedidos_completados"], 10)
        self.assertEqual(data["dias_validacion"], 2)
        self.assertEqual(len(data["predicciones"]), 1)
        prediction = data["predicciones"][0]
        self.assertEqual(Decimal(prediction["demanda_estimada"]), 308)
        self.assertEqual(Decimal(prediction["valor_metrica"]), 0)
        self.assertEqual(prediction["nombre_metrica"], "MAE")
        self.assertEqual(prediction["periodo_fin"], "2026-11-02")
        self.assertEqual(Decimal(data["insumos"][0]["cantidad_necesaria"]), Decimal("61.6"))
        self.assertEqual(Decimal(data["insumos"][0]["faltante"]), Decimal("41.6"))
        saved = self.client.get(BASE + "/predicciones")
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["predicciones"][0]["id_prediccion"], prediction["id_prediccion"])

    def test_owner_scope_roles_and_csrf(self):
        self.assertEqual(self.client.get("/api/restaurantes/2/predicciones").status_code, 403)
        self.assertEqual(self.client.post(BASE + "/predicciones").status_code, 403)
        for user in (1, 3, 5, 8):
            self.sign_in(user)
            self.assertEqual(self.generate().status_code, 403)
            self.assertEqual(self.client.get(BASE + "/predicciones").status_code, 403)

    def test_validation_is_out_of_sample_and_missing_recipes_are_explicit(self):
        with Session(self.engine) as db:
            ids = historical_orders(db)
            # Picos solo en los días reservados: MAE debe mostrar error real.
            rows = db.scalars(select(DetallePedido).join(Pedido).where(Pedido.id_pedido.in_(ids))).all()
            for row in rows:
                if row.id_pedido in {ids[5], ids[6]}:
                    row.cantidad = 1000
            db.delete(db.get(RecetaDetalle, (1, 1)))
            db.commit()
        response = self.generate()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreater(Decimal(response.json()["predicciones"][0]["valor_metrica"]), 900)
        self.assertEqual(response.json()["insumos"], [])
        self.assertEqual(response.json()["recetas_faltantes"], ["Pizza sintética"] if self.engine.dialect.name == "sqlite" else ["Producto sintético 1"])


PERIOD = {"inicio": "2026-10-25", "fin": "2026-10-26"}


def indicator_history(db):
    db.get(Pedido, 1).fecha_hora = datetime(2020, 1, 1, tzinfo=UTC)
    for day, price, prep, delivery in ((23, 100, 10, 20), (25, 110, 11, 22), (26, 111, 12, 23)):
        start = datetime(2026, 10, day, 10, tzinfo=UTC)
        order = add_order(db, estado="Entregado", fecha_hora=start, importe_total=price)
        for type, state, timestamp in (("preparacion", "En preparación", start),
                                       ("estado", "Listo", start + timedelta(minutes=prep)),
                                       ("entrega", "En camino", start + timedelta(hours=1)),
                                       ("entrega", "Entregado", start + timedelta(hours=1, minutes=delivery))):
            db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=1, tipo_evento=type, estado=state,
                                  fecha_hora=timestamp, detalle="Fixture de indicadores"))
    db.get(Insumo, 1).stock_actual = Decimal("-1")
    db.get(Insumo, 3).stock_actual = Decimal("-999")  # Otro restaurante: debe quedar aislado.
    db.commit()


class IndicatorTests(unittest.TestCase):
    setUp = ForecastTests.setUp
    configure_client = ForecastTests.configure_client
    sign_in = ForecastTests.sign_in

    def evaluate(self, period=None):
        return self.client.post(BASE + "/indicadores", headers=HEADERS, json=PERIOD if period is None else period)

    def test_real_durations_reference_strict_threshold_deduplication_and_resolution(self):
        with Session(self.engine) as db:
            indicator_history(db)
        for _ in range(2):
            response = self.evaluate()
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(Decimal(data["promedios"]["importe"]), Decimal("110.5"))
            self.assertEqual(Decimal(data["promedios"]["preparacion"]), Decimal("11.5"))
            self.assertEqual(Decimal(data["promedios"]["entrega"]), Decimal("22.5"))
            self.assertEqual(data["muestras_referencia"], {"importe": 1, "preparacion": 1, "entrega": 1})
            self.assertEqual({row["tipo"] for row in data["alertas"]}, {"importe", "preparacion", "entrega", "stock"})
            self.assertEqual(len(data["alertas"]), 4)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Alerta)), 4)
            db.get(Insumo, 1).stock_actual = 10
            db.commit()
        result = self.evaluate().json()
        self.assertEqual(next(row["estado"] for row in result["alertas"] if row["tipo"] == "stock"), "Resuelta")
        self.assertEqual(len(self.client.get(BASE + "/alertas").json()), 4)

    def test_without_baseline_no_average_or_threshold_is_invented(self):
        response = self.evaluate({"inicio": "2019-01-01", "fin": "2019-01-02"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(all(value is None for value in response.json()["promedios"].values()))
        self.assertTrue(all(value is None for value in response.json()["promedios_referencia"].values()))
        self.assertEqual(response.json()["alertas"], [])

    def test_repeated_preparation_measures_only_the_completed_cycle(self):
        with Session(self.engine) as db:
            indicator_history(db)
            order = db.scalar(select(Pedido).where(Pedido.fecha_hora == datetime(2026, 10, 26, 10, tzinfo=UTC)))
            db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=1, tipo_evento="preparacion", estado="En preparación",
                                  fecha_hora=datetime(2026, 10, 26, 9, tzinfo=UTC)))
            db.commit()
        response = self.evaluate()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(Decimal(response.json()["promedios"]["preparacion"]), Decimal("11.5"))

    def test_permissions_future_invalid_period_and_csrf(self):
        for payload in ({"inicio": "2026-10-27", "fin": "2026-10-26"},
                        {"inicio": "2027-01-01", "fin": "2027-01-02"},
                        {"inicio": "0001-01-01", "fin": "0001-01-02"}):
            self.assertEqual(self.evaluate(payload).status_code, 422)
        self.assertEqual(self.client.post(BASE + "/indicadores", json=PERIOD).status_code, 403)
        self.assertEqual(self.client.get("/api/restaurantes/2/alertas").status_code, 403)
        for user in (1, 3, 5, 8):
            self.sign_in(user)
            self.assertEqual(self.evaluate().status_code, 403)
            self.assertEqual(self.client.get(BASE + "/alertas").status_code, 403)
