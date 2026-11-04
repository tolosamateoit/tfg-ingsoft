"""Circuitos integrados y permisos de las funcionalidades completadas; datos descartables."""

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.couriers import router as couriers_router
from app.api.menu import router as menu_router
from app.api.preparation import router as preparation_router
from app.api.logistics import router as logistics_router
from app.db.models import Entrega, HistorialPedido, Insumo, MovimientoStock, Pedido, RecetaDetalle, Repartidor, Usuario
from app.auth.security import verify_password
from app.auth.service import as_utc
from app.couriers.earnings import BUENOS_AIRES
from tests.auth_support import HEADERS, PASSWORD
from tests import test_orders

ORDER = test_orders.ORDER

BASE = "/api/restaurantes/1"
COURIER = {"nombre": "Santiago Molina", "correo": "santiago@example.invalid", "contrasena": "Una frase segura 47"}
INGREDIENT = {"nombre": "Aceite de oliva", "unidad": "l", "costo_unitario": "3200.50"}


class CompletionTests(unittest.TestCase):
    setUp = test_orders.OrderReadTests.setUp
    sign_in = test_orders.OrderReadTests.sign_in

    def configure_client(self):
        test_orders.OrderReadTests.configure_client(self)
        for router in (menu_router, couriers_router, preparation_router, logistics_router):
            self.app.include_router(router, prefix="/api")
        if self.engine.dialect.name == "sqlite":
            for target in ("app.menu.inventory.lock_recipe_relations", "app.menu.service.lock_recipe_relations",
                           "app.couriers.service.lock_order_relations", "app.couriers.service.lock_email",
                           "app.preparation.service.lock_order_relations", "app.logistics.service.lock_order_relations"):
                context = patch(target)
                context.start()
                self.addCleanup(context.stop)

    def post(self, path, data):
        return self.client.post(path, headers=HEADERS, json=data)

    def put(self, path, data):
        return self.client.put(path, headers=HEADERS, json=data)

    def test_customer_confirmation_identity_distance_persistence_and_server_prices(self):
        payload = {key: value for key, value in ORDER.items() if key != "correo_cliente"}
        response = self.post(BASE + "/pedidos", payload)
        self.assertEqual(response.status_code, 201, response.text)
        id = response.json()["id_pedido"]
        self.assertEqual(response.json()["distancia_km"], "2.00")
        self.assertEqual(response.json()["importe_total"], "300.00")
        for _ in range(2):
            self.assertEqual(self.client.get(f"/api/pedidos/{id}").json()["distancia_km"], "2.00")
        with Session(self.engine) as db:
            order = db.get(Pedido, id)
            self.assertEqual(order.id_cliente, 1)
            self.assertEqual(order.historial[0].id_usuario, 3)
        self.assertEqual(self.post(BASE + "/pedidos", ORDER).status_code, 422)
        self.sign_in(4)
        self.assertEqual(self.client.get(f"/api/pedidos/{id}").status_code, 404)

    def test_product_presentation_persists_and_is_visible_without_internal_costs(self):
        self.sign_in(1)
        product = {"nombre": "Pizza Margarita", "precio": "9500", "costo_unitario": "3200", "activo": True,
                   "descripcion": "Mozzarella, tomate y albahaca.", "imagen_url": "/images/pizza.jpg"}
        response = self.put(BASE + "/productos/1", product)
        self.assertEqual(response.status_code, 200, response.text)
        for url in ("javascript:alert(1)", "data:image/svg+xml,test", "//example.invalid/pizza.jpg", "/images/../secret", "https://user:password@example.invalid/x"):
            self.assertEqual(self.put(BASE + "/productos/1", {**product, "imagen_url": url}).status_code, 422)
        self.sign_in(3)
        item = self.client.get(BASE + "/menu").json()["productos"][0]
        self.assertEqual(item["descripcion"], product["descripcion"])
        self.assertEqual(item["imagen_url"], product["imagen_url"])
        self.assertNotIn("costo_unitario", item)

    def test_customer_unavailable_delivery_and_foreign_products_rejected(self):
        payload = {key: value for key, value in ORDER.items() if key != "correo_cliente"}
        self.assertEqual(self.post(BASE + "/pedidos", {**payload, "detalles": [{"id_producto": 2, "cantidad": 1}]}).status_code, 422)
        with Session(self.engine) as db:
            for id in (1, 3):
                db.get(Repartidor, id).estado_disponibilidad = "Ocupado"
            db.commit()
        self.assertEqual(self.post(BASE + "/pedidos", payload).status_code, 409)
        self.assertEqual(self.client.get(BASE + "/menu").status_code, 200)

    def test_inventory_replenishment_adjustment_and_isolation(self):
        self.sign_in(1)
        response = self.post(BASE + "/insumos", INGREDIENT)
        self.assertEqual(response.status_code, 201, response.text)
        id = response.json()["id_insumo"]
        self.assertEqual(Decimal(response.json()["stock_actual"]), 0)
        path = f"{BASE}/insumos/{id}/movimientos"
        for kind, quantity, expected in (("reposicion", "4.123456", "4.123456"), ("ajuste", "-4", "0.123456")):
            result = self.post(path, {"tipo": kind, "cantidad": quantity, "motivo": "Recuento de cocina"})
            self.assertEqual(result.status_code, 201, result.text)
            self.assertEqual(Decimal(result.json()["stock_actual"]), Decimal(expected))
        self.assertEqual(self.put(f"{BASE}/insumos/{id}", {**INGREDIENT, "unidad": "kg"}).status_code, 409)
        self.assertEqual(self.put(f"{BASE}/insumos/{id}", {**INGREDIENT, "nombre": "Aceite"}).status_code, 200)
        history = self.client.get(BASE + "/movimientos-stock").json()
        self.assertEqual(len(history), 2)
        self.assertTrue(all(row["id_pedido"] is None and "Usuario #1" in row["motivo"] for row in history))
        self.assertEqual(self.post(BASE + "/insumos/3/movimientos", {"tipo": "ajuste", "cantidad": 1, "motivo": "Recuento"}).status_code, 404)
        self.assertEqual(self.client.get("/api/restaurantes/2/movimientos-stock").status_code, 403)
        self.sign_in(3)
        self.assertEqual(self.client.get(BASE + "/movimientos-stock").status_code, 403)
        self.assertEqual(self.post(BASE + "/insumos", INGREDIENT).status_code, 403)

    def test_inventory_invalid_movements_do_not_change_stock(self):
        self.sign_in(1)
        path = BASE + "/insumos/1/movimientos"
        for change in ({"cantidad": "0"}, {"cantidad": "-1"}, {"cantidad": "NaN"}, {"cantidad": "0.0000001"},
                       {"cantidad": "1000000000000"}, {"motivo": " "}, {"tipo": "consumo"}, {"id_pedido": 1}):
            result = self.post(path, {"tipo": "reposicion", "cantidad": "1", "motivo": "Compra", **change})
            self.assertEqual(result.status_code, 422, result.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, 20)
            self.assertEqual(db.scalar(select(func.count()).select_from(MovimientoStock)), 0)
        self.assertEqual(self.client.post(path, json={"tipo": "ajuste", "cantidad": 1, "motivo": "Recuento"}).status_code, 403)

    def test_preparation_consumption_is_visible_in_shared_inventory_once(self):
        self.sign_in(1)
        with Session(self.engine) as db:
            db.add(RecetaDetalle(id_producto=1, id_insumo=1, cantidad=Decimal("0.2"), unidad="kg"))
            db.commit()
        path = BASE + "/pedidos/1/preparacion"
        result = self.put(path, {"estado": "En preparación", "version": 0})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.put(path, {"estado": "En preparación", "version": 0}).status_code, 200)
        history = self.client.get(BASE + "/movimientos-stock").json()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["id_pedido"], 1)
        self.assertEqual(history[0]["tipo"], "consumo")
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, Decimal("19.8"))

    def test_owner_courier_creation_credentials_duplicate_and_restaurant(self):
        self.sign_in(7)
        response = self.post(BASE + "/repartidores", COURIER)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("contrasena", response.text)
        self.assertEqual(response.json()["estado_disponibilidad"], "No disponible")
        with Session(self.engine) as db:
            account = db.scalar(select(Usuario).where(Usuario.correo == COURIER["correo"]))
            self.assertEqual(account.id_restaurante, 1)
            self.assertEqual(account.rol, "repartidor")
            self.assertTrue(verify_password(account.hash_contrasena, COURIER["contrasena"]))
            self.assertEqual(len(account.repartidor.historial), 1)
        self.assertEqual(self.post(BASE + "/repartidores", {**COURIER, "correo": COURIER["correo"].upper()}).status_code, 409)
        self.assertEqual(self.post(BASE + "/repartidores", {**COURIER, "correo": "u6@test.invalid"}).status_code, 409)
        self.assertEqual(self.post("/api/restaurantes/2/repartidores", COURIER).status_code, 403)
        self.client.cookies.clear()
        login = self.post("/api/auth/login", {"correo": COURIER["correo"], "contrasena": COURIER["contrasena"]})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.json()["rol"], "repartidor")

    def test_only_owner_creates_couriers_or_configures_rates(self):
        for id in (1, 3, 5, 8):
            self.sign_in(id)
            self.assertEqual(self.post(BASE + "/repartidores", COURIER).status_code, 403)
            self.assertEqual(self.put(BASE + "/tarifas", {"costo_fijo_entrega": 100, "costo_por_km": 20}).status_code, 403)
        self.sign_in(7)
        for password in ("123456789012345", "corta", "a" * 16):
            self.assertEqual(self.post(BASE + "/repartidores", {**COURIER, "contrasena": password}).status_code, 422)
        for value in ("-1", "NaN", "1.001"):
            self.assertEqual(self.put(BASE + "/tarifas", {"costo_fijo_entrega": value, "costo_por_km": 20}).status_code, 422)

    def test_economics_owner_only_and_current_rate_breakdown(self):
        self.sign_in(7)
        rates = self.put(BASE + "/tarifas", {"costo_fijo_entrega": "40.50", "costo_por_km": "2.25"})
        self.assertEqual(rates.status_code, 200, rates.text)
        response = self.client.get("/api/pedidos/1").json()
        economy = response["economia"]
        self.assertEqual(economy["importe_productos"], "100.00")
        self.assertEqual(economy["costo_productos"], "10.00")
        self.assertEqual(economy["costo_entrega"], "42.75")
        self.assertEqual(economy["margen_estimado"], "47.25")
        for id in (1, 3):
            self.sign_in(id)
            self.assertIsNone(self.client.get("/api/pedidos/1").json()["economia"])

    def test_timers_ignore_distance_events_and_use_last_preparation_cycle(self):
        start = datetime(2026, 10, 30, 10, tzinfo=UTC)
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = "Entregado"
            for minute, kind, state in ((0, "preparacion", "En preparación"), (2, "estado", "Listo"),
                (3, "nueva_preparacion", "En preparación"), (8, "estado", "Listo"),
                (9, "distancia", "Listo"), (10, "asignacion", "Asignado"),
                (11, "entrega", "En camino"), (18, "entrega", "Entregado"), (19, "distancia", "Entregado")):
                db.add(HistorialPedido(id_pedido=1, id_usuario=1, fecha_hora=start + timedelta(minutes=minute),
                                      tipo_evento=kind, estado=state))
            db.commit()
        result = self.client.get("/api/pedidos/1").json()
        self.assertEqual(Decimal(result["preparacion_minutos"]), 5)
        self.assertEqual(Decimal(result["entrega_minutos"]), 7)
        self.assertTrue(result["estado_desde"].startswith("2026-10-30T10:18"))
        listed = self.client.get("/api/pedidos").json()["pedidos"]
        self.assertTrue(next(row for row in listed if row["id_pedido"] == 1)["estado_desde"].startswith("2026-10-30T10:18"))

    def test_daily_earnings_completion_day_isolation_and_saved_cost(self):
        self.sign_in(5)
        with Session(self.engine) as db:
            # La fecha del pedido no determina el día de finalización.
            db.get(Pedido, 1).fecha_hora = datetime(2020, 1, 1, tzinfo=UTC)
            delivery = db.scalar(select(Entrega).where(Entrega.id_pedido == 1))
            delivery.estado = "Entregado"
            delivery.costo_repartidor = Decimal("1234.56")
            db.add(HistorialPedido(id_pedido=1, id_usuario=5, tipo_evento="entrega", estado="Entregado"))
            db.commit()
        result = self.client.get("/api/repartidores/me/resumen-diario")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["entregas_completadas"], 1)
        self.assertEqual(result.json()["importe_estimado"], "1234.56")
        self.sign_in(6)
        self.assertEqual(self.client.get("/api/repartidores/me/resumen-diario").json()["entregas_completadas"], 0)
        self.sign_in(3)
        self.assertEqual(self.client.get("/api/repartidores/me/resumen-diario").status_code, 403)

    def test_daily_earnings_use_buenos_aires_midnight_boundaries(self):
        self.sign_in(5)
        with Session(self.engine) as db:
            today = as_utc(db.scalar(select(func.now()))).astimezone(BUENOS_AIRES).date()
            start = datetime.combine(today, datetime.min.time(), BUENOS_AIRES).astimezone(UTC)
            delivery = db.scalar(select(Entrega).where(Entrega.id_pedido == 1))
            delivery.estado = "Entregado"
            event = HistorialPedido(id_pedido=1, id_usuario=5, tipo_evento="entrega", estado="Entregado", fecha_hora=start)
            db.add(event)
            db.commit()
            id = event.id_historial
        path = "/api/repartidores/me/resumen-diario"
        self.assertEqual(self.client.get(path).json()["entregas_completadas"], 1)
        for timestamp in (start - timedelta(seconds=1), start + timedelta(days=1)):
            with Session(self.engine) as db:
                db.get(HistorialPedido, id).fecha_hora = timestamp
                db.commit()
            self.assertEqual(self.client.get(path).json()["entregas_completadas"], 0)


if __name__ == "__main__":
    unittest.main()
