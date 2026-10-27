"""HU-03: consultas HTTP con sesión y aislamiento real de las consultas SQL."""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.orders import router as orders_router
from app.db.models import Producto, Repartidor, Restaurante, Usuario
from tests.auth_support import HEADERS, PASSWORD, override_database
from tests.menu_support import sqlite_menu_engine


class OrderReadTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        lock = patch("app.auth.service.lock_email")
        lock.start()
        self.addCleanup(lock.stop)
        self.configure_client()

    def configure_client(self):
        self.app = FastAPI()
        self.app.include_router(auth_router, prefix="/api")
        self.app.include_router(orders_router, prefix="/api")
        override_database(self.app, self.engine)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.sign_in(3)

    def sign_in(self, user):
        self.client.cookies.clear()
        response = self.client.post("/api/auth/login", headers=HEADERS,
                                    json={"correo": f"u{user}@test.invalid", "contrasena": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)

    def test_menu_shows_only_active_products_without_internal_costs(self):
        with Session(self.engine) as db:
            db.get(Producto, 2).activo = False
            db.commit()
        first = self.client.get("/api/restaurantes/1/menu")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual([p["id_producto"] for p in first.json()["productos"]], [1])
        self.assertEqual(set(first.json()["productos"][0]), {"id_producto", "nombre", "precio"})
        self.assertEqual(self.client.get("/api/restaurantes/2/menu").json()["productos"], [])
        self.assertEqual(self.client.get("/api/restaurantes/999/menu").status_code, 404)

    def test_closed_restaurant_keeps_menu_visible(self):
        with Session(self.engine) as db:
            db.get(Restaurante, 1).abierto = False
            db.commit()
        response = self.client.get("/api/restaurantes/1/menu")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["productos"])
        self.assertFalse(response.json()["restaurante"]["delivery_disponible"])

    def test_delivery_requires_available_active_courier_of_that_restaurant(self):
        with Session(self.engine) as db:
            db.get(Repartidor, 1).estado_disponibilidad = "Ocupado"
            db.get(Usuario, 9).activo = False
            db.commit()
        restaurants = self.client.get("/api/restaurantes").json()
        self.assertEqual({r["id_restaurante"]: r["delivery_disponible"] for r in restaurants},
                         {1: False, 2: True})

    def test_customer_sees_only_own_orders_across_restaurants(self):
        response = self.client.get("/api/pedidos")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({r["id_pedido"] for r in response.json()["pedidos"]}, {1, 3})
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(self.client.get("/api/pedidos/2").status_code, 404)
        self.sign_in(4)
        self.assertEqual({r["id_pedido"] for r in self.client.get("/api/pedidos").json()["pedidos"]}, {2})
        self.assertEqual(self.client.get("/api/pedidos/1").status_code, 404)

    def test_staff_and_owner_only_see_their_restaurant(self):
        for user in (1, 7):
            self.sign_in(user)
            response = self.client.get("/api/pedidos")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual({r["id_pedido"] for r in response.json()["pedidos"]}, {1})
            self.assertEqual(self.client.get("/api/pedidos/3").status_code, 404)
        self.sign_in(2)
        self.assertEqual({r["id_pedido"] for r in self.client.get("/api/pedidos").json()["pedidos"]}, {2, 3})

    def test_details_have_snapshot_price_and_no_private_cost(self):
        response = self.client.get("/api/pedidos/1")
        self.assertEqual(response.status_code, 200, response.text)
        order = response.json()
        self.assertEqual(order["estado"], "Nuevo")
        self.assertEqual(order["importe_total"], "100.00")
        self.assertEqual(order["detalles"][0]["subtotal"], "100.00")
        self.assertNotIn("costo_total", order)
        self.assertNotIn("id_usuario", order)

    def test_pagination_and_input_bounds(self):
        response = self.client.get("/api/pedidos?limit=1&offset=1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(len(response.json()["pedidos"]), 1)
        for query in ("limit=0", "limit=101", "offset=-1"):
            self.assertEqual(self.client.get(f"/api/pedidos?{query}").status_code, 422)

    def test_roles_and_anonymous_access(self):
        for user in (5, 8):
            self.sign_in(user)
            for path in ("/api/pedidos", "/api/pedidos/1", "/api/restaurantes", "/api/restaurantes/1/menu"):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.client.cookies.clear()
        for path in ("/api/pedidos", "/api/pedidos/1", "/api/restaurantes", "/api/restaurantes/1/menu"):
            self.assertEqual(self.client.get(path).status_code, 401)
