"""HU-03: consultas HTTP con sesión y aislamiento real de las consultas SQL."""

import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.orders import router as orders_router
from app.db.models import DetallePedido, Entrega, HistorialPedido, Insumo, MovimientoStock, Pedido, Producto, RecetaDetalle, Repartidor, Restaurante, Usuario
from tests.auth_support import HEADERS, PASSWORD, override_database
from tests.menu_support import sqlite_menu_engine

ORDER = {"correo_cliente": "u3@test.invalid", "direccion_entrega": " Calle de prueba 123 ",
         "referencia_local": "Puerta verde", "zona_entrega": "Centro", "medio_pago": "efectivo", "distancia_km": "2",
         "detalles": [{"id_producto": 1, "cantidad": 3}]}
CREATE = "/api/restaurantes/1/pedidos"


class OrderReadTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        lock = patch("app.auth.service.lock_email")
        lock.start()
        self.addCleanup(lock.stop)
        relations = patch("app.orders.service.lock_order_relations")
        relations.start()
        self.addCleanup(relations.stop)
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
        self.assertEqual(set(first.json()["productos"][0]), {"id_producto", "nombre", "precio", "descripcion", "imagen_url"})
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
            db.get(Repartidor, 1).estado_disponibilidad = "No disponible"
            db.get(Usuario, 9).activo = False
            db.commit()
        restaurants = self.client.get("/api/restaurantes").json()
        self.assertEqual({r["id_restaurante"]: r["delivery_disponible"] for r in restaurants},
                         {1: True, 2: True})

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
        self.sign_in(5)
        self.assertEqual(self.client.get('/api/pedidos/1').status_code, 200)
        self.assertEqual(self.client.get('/api/pedidos/2').status_code, 404)
        self.assertEqual(self.client.get('/api/restaurantes').status_code, 403)
        for user in (8,):
            self.sign_in(user)
            for path in ("/api/pedidos", "/api/pedidos/1", "/api/restaurantes", "/api/restaurantes/1/menu"):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.client.cookies.clear()
        for path in ("/api/pedidos", "/api/pedidos/1", "/api/restaurantes", "/api/restaurantes/1/menu"):
            self.assertEqual(self.client.get(path).status_code, 401)

    def post_order(self, data=None, user=1):
        payload = ORDER if data is None else data
        with Session(self.engine) as db:
            for item in payload.get('detalles', []):
                product = db.get(Producto, item.get('id_producto'))
                if product is not None and product.id_restaurante == 1 and not db.scalar(select(RecetaDetalle.id_producto).where(RecetaDetalle.id_producto == product.id_producto).limit(1)):
                    db.add(RecetaDetalle(id_producto=product.id_producto, id_insumo=1, cantidad=Decimal('.1'), unidad='kg'))
            db.commit()
        self.sign_in(user)
        return self.client.post(CREATE, headers=HEADERS, json=payload)

    def test_create_one_product_with_server_totals_and_initial_history(self):
        response = self.post_order()
        self.assertEqual(response.status_code, 201, response.text)
        saved = response.json()
        self.assertEqual(saved["importe_total"], "300.00")
        self.assertEqual(saved["direccion_entrega"], "Calle de prueba 123")
        with Session(self.engine) as db:
            order = db.get(Pedido, saved["id_pedido"])
            self.assertEqual(order.costo_total, Decimal("30.00"))
            self.assertEqual(order.distancia_km, Decimal("2"))
            self.assertEqual(saved["distancia_km"], "2.00")
            self.assertEqual(order.id_cliente, 1)
            self.assertEqual(order.estado, "Nuevo")
            self.assertEqual(order.estado_pago, "pendiente")
            self.assertIsNone(order.puntaje_prioridad)
            self.assertIsNone(order.factores_prioridad)
            self.assertEqual(len(order.detalles), 1)
            self.assertEqual(len(order.historial), 1)
            self.assertEqual(order.historial[0].id_usuario, 1)
            self.assertEqual(order.historial[0].estado, "Nuevo")
        self.sign_in(3)
        self.assertEqual(self.client.get(f'/api/pedidos/{saved["id_pedido"]}').status_code, 200)

    def test_multiple_products_exact_totals_and_price_snapshot(self):
        with Session(self.engine) as db:
            db.get(Producto, 1).precio = Decimal("12.34")
            db.get(Producto, 1).costo_unitario = Decimal("4.56")
            product = Producto(id_restaurante=1, nombre="Otro producto", precio=Decimal("0.01"),
                               costo_unitario=Decimal("0.02"), activo=True)
            db.add(product); db.commit()
            product_id = product.id_producto
        response = self.post_order({**ORDER, "detalles": [{"id_producto": 1, "cantidad": 3},
                                                          {"id_producto": product_id, "cantidad": 7}]}, user=7)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["importe_total"], "37.09")
        with Session(self.engine) as db:
            self.assertEqual(db.get(Pedido, response.json()["id_pedido"]).costo_total, Decimal("13.82"))
            db.get(Producto, 1).precio = Decimal("99")
            db.commit()
        detail = self.client.get(f'/api/pedidos/{response.json()["id_pedido"]}').json()
        self.assertEqual(detail["detalles"][0]["precio_unitario"], "12.34")

    def test_closed_or_unavailable_delivery_rejects_without_writes(self):
        with Session(self.engine) as db:
            db.get(Restaurante, 1).abierto = False
            db.commit()
        self.assertEqual(self.post_order().status_code, 409)
        with Session(self.engine) as db:
            db.get(Restaurante, 1).abierto = True
            for courier_id in (1, 3):
                db.get(Repartidor, courier_id).estado_disponibilidad = "No disponible"
            db.commit()
        self.assertEqual(self.post_order().status_code, 201)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Pedido)), 4)

    def test_invalid_foreign_inactive_and_nonexistent_products(self):
        for product in (2, 999):
            self.assertEqual(self.post_order({**ORDER, "detalles": [{"id_producto": product, "cantidad": 1}]}).status_code, 422)
        with Session(self.engine) as db:
            db.get(Producto, 1).activo = False
            db.commit()
        self.assertEqual(self.post_order().status_code, 422)

    def test_invalid_payloads_and_server_fields_are_rejected(self):
        for change in ({"detalles": []}, {"detalles": ORDER["detalles"] * 2},
                       {"detalles": [{"id_producto": 1, "cantidad": 0}]},
                       {"detalles": [{"id_producto": 1, "cantidad": 1.5}]},
                       {"detalles": [{"id_producto": 1, "cantidad": True}]},
                       {"detalles": [{"id_producto": 1, "cantidad": 2147483648}]},
                       {"direccion_entrega": " "}, {"medio_pago": " "}, {"distancia_km": "-1"},
                       {"distancia_km": "1.0001"}, {"distancia_km": "NaN"},
                       {"distancia_km": "1000000000"}, {"importe_total": "0"}, {"costo_total": "0"},
                       {"id_cliente": 2}, {"estado": "Entregado"}, {"id_restaurante": 2}):
            with self.subTest(change=change):
                self.assertEqual(self.post_order({**ORDER, **change}).status_code, 422)

    def test_creation_permissions_and_csrf_are_required(self):
        for user in (2, 5, 8):
            self.assertEqual(self.post_order(user=user).status_code, 403)
        self.assertEqual(self.post_order(user=3).status_code, 422)  # No puede seleccionar otro cliente por correo.
        self.sign_in(1)
        self.assertEqual(self.client.post(CREATE, json=ORDER).status_code, 403)
        self.assertEqual(self.client.post("/api/restaurantes/2/pedidos", headers=HEADERS, json=ORDER).status_code, 403)

    def test_client_must_exist_and_be_active(self):
        for email in ("missing@test.invalid", "u1@test.invalid"):
            self.assertEqual(self.post_order({**ORDER, "correo_cliente": email}).status_code, 422)
        with Session(self.engine) as db:
            db.get(Usuario, 3).activo = False
            db.commit()
        self.assertEqual(self.post_order().status_code, 422)

    def test_numeric_overflow_is_rejected_before_write(self):
        with Session(self.engine) as db:
            db.get(Producto, 1).costo_unitario = Decimal("6000000000000000.00")
            db.commit()
        self.assertEqual(self.post_order().status_code, 422)

    def test_failure_rolls_back_header_details_and_history(self):
        def fail(*args):
            raise IntegrityError("synthetic failure", {}, Exception("fixture"))
        event.listen(DetallePedido, "before_insert", fail)
        try:
            response = self.post_order()
        finally:
            event.remove(DetallePedido, "before_insert", fail)
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Pedido)), 3)
            self.assertEqual(db.scalar(select(func.count()).select_from(DetallePedido)), 3)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido)), 0)

    def test_creating_does_not_consume_stock_or_assign_courier(self):
        with Session(self.engine) as db:
            before = dict(db.execute(select(Insumo.id_insumo, Insumo.stock_actual)).all())
            deliveries = db.scalar(select(func.count()).select_from(Entrega))
        self.assertEqual(self.post_order().status_code, 201)
        with Session(self.engine) as db:
            self.assertEqual(dict(db.execute(select(Insumo.id_insumo, Insumo.stock_actual)).all()), before)
            self.assertEqual(db.scalar(select(func.count()).select_from(MovimientoStock)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Entrega)), deliveries)
