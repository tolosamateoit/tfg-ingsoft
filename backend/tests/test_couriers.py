import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.couriers import router as couriers_router
from app.api.orders import router as orders_router
from app.db.models import HistorialRepartidor, RecetaDetalle, Repartidor, Usuario
from app.main import validation_error
from tests.auth_support import HEADERS, PASSWORD, override_database
from tests.menu_support import sqlite_menu_engine
from tests.test_orders import ORDER

BASE = "/api/restaurantes/1/repartidores"


class CourierTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        for target in ("app.auth.service.lock_email", "app.orders.service.lock_order_relations", "app.couriers.service.lock_order_relations"):
            context = patch(target)
            context.start()
            self.addCleanup(context.stop)
        self.configure_client()

    def configure_client(self):
        self.app = FastAPI()
        for router in (auth_router, orders_router, couriers_router):
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

    def update(self, id=1, estado="No disponible"):
        return self.client.put(f"{BASE}/{id}", headers=HEADERS, json={"estado_disponibilidad": estado})

    def test_list_and_changes_with_timestamp_are_scoped_and_idempotent(self):
        rows = self.client.get(BASE).json()["repartidores"]
        self.assertEqual({row["id_repartidor"] for row in rows}, {1, 3})
        self.assertTrue(all(row["ultimo_cambio"] is None for row in rows))
        self.sign_in(5)
        for _ in range(2):
            response = self.client.put('/api/repartidores/me', headers=HEADERS, json={'estado_disponibilidad':'No disponible'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["ultimo_cambio"])
        with Session(self.engine) as db:
            self.assertEqual(db.get(Repartidor, 1).estado_disponibilidad, "No disponible")
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialRepartidor)), 1)

    def test_availability_changes_immediately_control_hu03_confirmation(self):
        with Session(self.engine) as db:
            db.add(RecetaDetalle(id_producto=1, id_insumo=1, cantidad=1, unidad='kg'))
            db.commit()
        for uid in (5, 9):
            self.sign_in(uid)
            self.assertEqual(self.client.put('/api/repartidores/me', headers=HEADERS, json={'estado_disponibilidad':'No disponible'}).status_code, 200)
        self.sign_in(1)
        self.assertFalse(self.client.get(BASE).json()["delivery_disponible"])
        response = self.client.post("/api/restaurantes/1/pedidos", headers=HEADERS, json=ORDER)
        self.assertEqual(response.status_code, 201, response.text)
        self.sign_in(5)
        own = self.client.get("/api/repartidores/me")
        self.assertEqual([row["id_repartidor"] for row in own.json()["repartidores"]], [1])
        response = self.client.put("/api/repartidores/me", headers=HEADERS, json={"estado_disponibilidad": "Disponible"})
        self.assertEqual(response.status_code, 409, response.text)  # tiene una entrega activa
        self.sign_in(9)
        response = self.client.put("/api/repartidores/me", headers=HEADERS, json={"estado_disponibilidad": "Disponible"})
        self.assertEqual(response.status_code, 200, response.text)
        self.sign_in(3)
        self.assertTrue(self.client.get("/api/restaurantes/1/menu").json()["restaurante"]["delivery_disponible"])
        self.sign_in(1)
        response = self.client.post("/api/restaurantes/1/pedidos", headers=HEADERS, json=ORDER)
        self.assertEqual(response.status_code, 201, response.text)

    def test_roles_scope_csrf_and_no_account_or_restaurant_edits(self):
        self.assertEqual(self.update(2).status_code, 403)
        self.assertEqual(self.client.get("/api/restaurantes/2/repartidores").status_code, 403)
        self.assertEqual(self.client.put(BASE + "/1", json={"estado_disponibilidad": "Ocupado"}).status_code, 403)
        self.assertEqual(self.client.get("/api/repartidores/me").status_code, 403)
        for payload in ({"estado_disponibilidad": "Otro"}, {"estado_disponibilidad": "Disponible", "id_usuario": 2},
                        {"estado_disponibilidad": "Disponible", "id_restaurante": 2}):
            self.assertEqual(self.client.put(BASE + "/1", headers=HEADERS, json=payload).status_code, 422)
        for user in (3, 5, 8):
            self.sign_in(user)
            self.assertEqual(self.client.get(BASE).status_code, 403)
            self.assertEqual(self.update().status_code, 403)
        self.sign_in(5)
        self.assertEqual(self.client.put("/api/repartidores/me", headers=HEADERS,
                                       json={"estado_disponibilidad": "Disponible", "id_repartidor": 3}).status_code, 422)
        self.sign_in(7)
        self.assertEqual(self.update(estado="Ocupado").status_code, 422)

    def test_inactive_account_cannot_be_made_available(self):
        with Session(self.engine) as db:
            db.get(Usuario, 5).activo = False
            db.get(Usuario, 9).activo = False
            db.commit()
        self.assertFalse(self.client.get(BASE).json()["delivery_disponible"])
        self.assertEqual(self.update(estado="Disponible").status_code, 403)

    def test_history_failure_rolls_back_availability(self):
        def fail(*args):
            raise IntegrityError("fixture", {}, Exception("synthetic failure"))
        self.sign_in(5)
        event.listen(HistorialRepartidor, "before_insert", fail)
        try:
            response = self.client.put('/api/repartidores/me', headers=HEADERS, json={'estado_disponibilidad':'No disponible'})
        finally:
            event.remove(HistorialRepartidor, "before_insert", fail)
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Repartidor, 1).estado_disponibilidad, "Disponible")
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialRepartidor)), 0)
