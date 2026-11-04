"""HU-04 funcional por HTTP; PostgreSQL verifica además locks e integridad real."""

import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.orders import router as orders_router
from app.api.preparation import router as preparation_router
from app.db.models import DetallePedido, HistorialPedido, Insumo, MovimientoStock, Pedido, Producto, RecetaDetalle
from app.main import validation_error
from tests.auth_support import HEADERS, PASSWORD, override_database
from tests.menu_support import sqlite_menu_engine

BASE = "/api/restaurantes/1"
PREP = BASE + "/pedidos/1/preparacion"


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        for target in ("app.auth.service.lock_email", "app.preparation.service.lock_order_relations"):
            context = patch(target)
            context.start()
            self.addCleanup(context.stop)
        self.configure_client()

    def configure_client(self):
        with Session(self.engine) as db:
            db.add_all([RecetaDetalle(id_producto=1, id_insumo=1, cantidad=Decimal("0.2"), unidad="kg"),
                        RecetaDetalle(id_producto=1, id_insumo=2, cantidad=Decimal("0.1"), unidad="l")])
            db.commit()
        self.app = FastAPI()
        for router in (auth_router, orders_router, preparation_router):
            self.app.include_router(router, prefix="/api")
        self.app.add_exception_handler(RequestValidationError, validation_error)
        override_database(self.app, self.engine)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.sign_in(1)

    def sign_in(self, user):
        self.client.cookies.clear()
        response = self.client.post("/api/auth/login", headers=HEADERS,
                                    json={"correo": f"u{user}@test.invalid", "contrasena": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)

    def change(self, estado="En preparación", **extra):
        version = self.client.get(PREP).json()["version"]
        return self.client.put(PREP, headers=HEADERS, json={"estado": estado, "version": version, **extra})

    def test_first_preparation_and_retries_consume_exactly_once(self):
        for _ in range(2):
            response = self.client.put(PREP, headers=HEADERS, json={"estado": "En preparación", "version": 0})
            self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(len(data["movimientos"]), 2)
        self.assertEqual(data["estado"], "En preparación")
        self.assertEqual(data["historial"][0]["usuario"], "Usuario sintético 1")
        self.assertTrue(data["historial"][0]["fecha_hora"])
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, Decimal("19.8"))
            self.assertEqual(db.get(Insumo, 2).stock_actual, Decimal("49.9"))
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido)), 1)
        self.sign_in(3)
        self.assertEqual(self.client.get("/api/pedidos/1").json()["estado"], "En preparación")

    def test_ready_does_not_consume_and_only_explicit_repeat_consumes_again(self):
        self.assertEqual(self.change().status_code, 200)
        ready = self.change("Listo")
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual(len(ready.json()["movimientos"]), 2)
        self.assertEqual(self.change().status_code, 409)
        payload = {"estado": "En preparación", "version": ready.json()["version"],
                   "nueva_preparacion": True, "motivo": "Preparación arruinada"}
        for expected in (200, 409):
            result = self.client.put(PREP, headers=HEADERS, json=payload)
            self.assertEqual(result.status_code, expected, result.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, Decimal("19.6"))
            self.assertEqual(db.scalar(select(func.count()).select_from(MovimientoStock)), 4)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido)), 3)

    def test_shared_ingredient_is_aggregated_across_products_and_quantities(self):
        with Session(self.engine) as db:
            product = Producto(id_restaurante=1, nombre="Otro", precio=1, costo_unitario=1, activo=True)
            db.add(product); db.flush()
            db.add(RecetaDetalle(id_producto=product.id_producto, id_insumo=1, cantidad=Decimal("0.1"), unidad="kg"))
            db.get(DetallePedido, 1).cantidad = 2
            db.add(DetallePedido(id_pedido=1, id_producto=product.id_producto, cantidad=3, precio_unitario=1))
            db.commit()
        response = self.change()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["movimientos"]), 2)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, Decimal("19.3"))
            self.assertEqual(db.get(Insumo, 2).stock_actual, Decimal("49.8"))

    def test_negative_stock_and_missing_recipe_are_rejected(self):
        with Session(self.engine) as db:
            db.get(Insumo, 1).stock_actual = Decimal(0)
            db.commit()
        self.assertEqual(self.change().status_code, 409)
        self.assertFalse(any(Decimal(row["stock_actual"]) < 0 for row in self.client.get(BASE + "/stock").json()))
        self.sign_in(2)
        response = self.client.put("/api/restaurantes/2/pedidos/2/preparacion", headers=HEADERS,
                                   json={"estado": "En preparación", "version": 0})
        self.assertEqual(response.status_code, 409)

    def test_permissions_scope_csrf_and_stock_isolation(self):
        self.assertEqual({row["id_insumo"] for row in self.client.get(BASE + "/stock").json()}, {1, 2})
        self.assertEqual(self.client.get(BASE + "/pedidos/2/preparacion").status_code, 404)
        self.assertEqual(self.client.get("/api/restaurantes/2/stock").status_code, 403)
        self.assertEqual(self.client.put(PREP, json={"estado": "Listo", "version": 0}).status_code, 403)
        for user in (3, 5, 8):
            self.sign_in(user)
            self.assertEqual(self.client.get(PREP).status_code, 403)
            self.assertEqual(self.client.get(BASE + "/stock").status_code, 403)
            self.assertEqual(self.client.put(PREP, headers=HEADERS, json={"estado": "Listo", "version": 0}).status_code, 403)
        self.sign_in(7)
        self.assertEqual(self.change().status_code, 200)

    def test_invalid_transitions_stale_version_and_repeat_without_reason(self):
        self.assertEqual(self.change("Listo").status_code, 409)
        self.assertEqual(self.change(nueva_preparacion=True, motivo="Intento").status_code, 409)
        self.assertEqual(self.change(version=999).status_code, 409)
        self.assertEqual(self.change(nueva_preparacion=True).status_code, 422)
        self.assertEqual(self.change(estado="Entregado").status_code, 422)

    def test_failure_rolls_back_stock_state_movements_and_history(self):
        def fail(*args):
            raise IntegrityError("fixture", {}, Exception("synthetic failure"))
        event.listen(MovimientoStock, "before_insert", fail)
        try:
            response = self.change()
        finally:
            event.remove(MovimientoStock, "before_insert", fail)
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Pedido, 1).estado, "Nuevo")
            self.assertEqual(db.get(Insumo, 1).stock_actual, Decimal(20))
            self.assertEqual(db.scalar(select(func.count()).select_from(MovimientoStock)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido)), 0)
