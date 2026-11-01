"""HU-02 por HTTP con sesión real; SQLite solo simula los advisory locks."""

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
from app.api.menu import router as menu_router
from app.db.models import Insumo, MovimientoStock, Producto, RecetaDetalle
from app.main import private_responses, validation_error
from tests.auth_support import HEADERS, PASSWORD, override_database
from tests.menu_support import sqlite_menu_engine

PRODUCT = {"nombre": "Empanada sintética", "precio": "1500.25", "costo_unitario": "700.12", "activo": True}
RECIPE = {"detalles": [{"id_insumo": 1, "cantidad": "0.123456", "unidad": "kg"},
                       {"id_insumo": 2, "cantidad": "0.2", "unidad": "l"}]}
BASE = "/api/restaurantes/1"


class MenuApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        for target in ("app.auth.service.lock_email", "app.menu.service.lock_recipe_relations"):
            context = patch(target)
            context.start()
            self.addCleanup(context.stop)
        self.configure_client()

    def configure_client(self):
        self.app = FastAPI()
        self.app.include_router(auth_router, prefix="/api")
        self.app.include_router(menu_router, prefix="/api")
        self.app.add_exception_handler(RequestValidationError, validation_error)
        self.app.middleware("http")(private_responses)
        override_database(self.app, self.engine)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.sign_in()

    def sign_in(self, user=1):
        self.client.cookies.clear()
        response = self.client.post("/api/auth/login", headers=HEADERS,
                                    json={"correo": f"u{user}@test.invalid", "contrasena": PASSWORD})
        self.assertEqual(response.status_code, 200)

    def put_recipe(self, data=RECIPE, product=1):
        return self.client.put(f"{BASE}/productos/{product}/receta", headers=HEADERS, json=data)

    def test_catalog_and_ingredients_filtered_by_restaurant(self):
        response = self.client.get(f"{BASE}/productos")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id_producto"] for row in response.json()], [1])
        supplies = self.client.get(f"{BASE}/insumos")
        self.assertEqual({row["id_insumo"] for row in supplies.json()}, {1, 2})
        self.assertTrue(all(set(row) == {"id_insumo", "nombre", "unidad", "stock_actual", "costo_unitario"} for row in supplies.json()))

    def test_create_and_edit_product_with_separate_price_and_cost(self):
        response = self.client.post(f"{BASE}/productos", headers=HEADERS, json=PRODUCT)
        self.assertEqual(response.status_code, 201, response.text)
        product_id = response.json()["id_producto"]
        self.assertEqual(response.json()["id_restaurante"], 1)
        change = {**PRODUCT, "nombre": "Nombre actualizado", "precio": "1800.01", "costo_unitario": "820.10", "activo": False}
        edited = self.client.put(f"{BASE}/productos/{product_id}", headers=HEADERS, json=change)
        self.assertEqual(edited.status_code, 200)
        with Session(self.engine) as db:
            product = db.get(Producto, product_id)
            self.assertEqual(product.nombre, "Nombre actualizado")
            self.assertEqual(product.precio, Decimal("1800.01"))
            self.assertEqual(product.costo_unitario, Decimal("820.10"))
            self.assertEqual(product.id_restaurante, 1)
            self.assertFalse(product.activo)

    def test_names_trimmed_and_zero_price_allowed(self):
        response = self.client.post(f"{BASE}/productos", headers=HEADERS,
                                    json={**PRODUCT, "nombre": "  Agua sin cargo  ", "precio": "0", "costo_unitario": "0"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["nombre"], "Agua sin cargo")

    def test_exponent_input_serialized_as_exact_decimal_for_ui(self):
        response = self.client.post(f"{BASE}/productos", headers=HEADERS,
                                    json={**PRODUCT, "precio": "1e6", "costo_unitario": "1e-2"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["precio"], "1000000.00")
        self.assertEqual(response.json()["costo_unitario"], "0.01")

    def test_invalid_products_rejected_without_writes(self):
        for change in (
            {"nombre": "   "}, {"nombre": "x" * 151}, {"precio": "-0.01"}, {"costo_unitario": "-1"},
            {"precio": "1.001"}, {"costo_unitario": "1.001"}, {"precio": "NaN"}, {"precio": "Infinity"},
            {"precio": "10000000000000000"}, {"activo": "true"}, {"id_restaurante": 2}, {"foto": "x"},
        ):
            with self.subTest(change=change):
                response = self.client.post(f"{BASE}/productos", headers=HEADERS, json={**PRODUCT, **change})
                self.assertEqual(response.status_code, 422)
        self.assertEqual(len(self.client.get(f"{BASE}/productos").json()), 1)

    def test_monetary_precision_not_rounded_silently(self):
        response = self.client.post(f"{BASE}/productos", headers=HEADERS,
                                    json={**PRODUCT, "precio": "9999999999999999.99"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decimal(response.json()["precio"]), Decimal("9999999999999999.99"))
        # SQLite usa REAL para NUMERIC; solo PostgreSQL certifica persistencia decimal exacta.
        if self.engine.dialect.name == "postgresql":
            with Session(self.engine) as db:
                self.assertEqual(db.get(Producto, response.json()["id_producto"]).precio, Decimal("9999999999999999.99"))

    def test_restaurant_and_known_foreign_product_ids_denied(self):
        for path in ("productos", "insumos", "productos/2/receta"):
            self.assertEqual(self.client.get(f"/api/restaurantes/2/{path}").status_code, 403)
        self.assertEqual(self.client.post("/api/restaurantes/2/productos", headers=HEADERS, json=PRODUCT).status_code, 403)
        self.assertEqual(self.client.put(f"{BASE}/productos/2", headers=HEADERS, json=PRODUCT).status_code, 404)
        self.assertEqual(self.client.get(f"{BASE}/productos/2/receta").status_code, 404)
        self.assertEqual(self.put_recipe(product=2).status_code, 404)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Producto, 2).id_restaurante, 2)

    def test_only_staff_and_owner_can_manage(self):
        for user in (3, 5, 8):
            self.sign_in(user)
            for path in ("productos", "insumos", "productos/1/receta"):
                self.assertEqual(self.client.get(f"{BASE}/{path}").status_code, 403)
            self.assertEqual(self.client.post(f"{BASE}/productos", headers=HEADERS, json=PRODUCT).status_code, 403)
            self.assertEqual(self.put_recipe().status_code, 403)
        self.sign_in(7)
        self.assertEqual(self.client.post(f"{BASE}/productos", headers=HEADERS, json=PRODUCT).status_code, 201)

    def test_session_and_csrf_are_required(self):
        self.assertEqual(self.client.post(f"{BASE}/productos", json=PRODUCT).status_code, 403)
        self.assertEqual(self.client.put(f"{BASE}/productos/1", json=PRODUCT).status_code, 403)
        self.assertEqual(self.client.put(f"{BASE}/productos/1/receta", json=RECIPE).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(f"{BASE}/productos").status_code, 401)
        self.assertEqual(self.client.post(f"{BASE}/productos", headers=HEADERS, json=PRODUCT).status_code, 401)

    def test_save_reload_replace_and_clear_recipe(self):
        response = self.put_recipe()
        self.assertEqual(response.status_code, 200, response.text)
        loaded = self.client.get(f"{BASE}/productos/1/receta").json()
        by_id = {row["id_insumo"]: row for row in loaded["detalles"]}
        self.assertEqual(Decimal(by_id[1]["cantidad"]), Decimal("0.123456"))
        self.assertEqual(by_id[1]["unidad"], "kg")
        self.assertEqual(self.put_recipe({"detalles": [RECIPE["detalles"][0]]}).status_code, 200)
        self.assertEqual(len(self.client.get(f"{BASE}/productos/1/receta").json()["detalles"]), 1)
        self.assertEqual(self.put_recipe({"detalles": []}).status_code, 200)
        self.assertEqual(self.client.get(f"{BASE}/productos/1/receta").json()["detalles"], [])

    def test_foreign_and_missing_ingredient_keep_original_recipe(self):
        self.put_recipe()
        original = self.client.get(f"{BASE}/productos/1/receta").json()
        for item in ({"id_insumo": 3, "cantidad": "1", "unidad": "kg"},
                     {"id_insumo": 999, "cantidad": "1", "unidad": "kg"}):
            response = self.put_recipe({"detalles": [RECIPE["detalles"][0], item]})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(self.client.get(f"{BASE}/productos/1/receta").json(), original)

    def test_invalid_quantities_duplicates_and_units_rejected(self):
        self.put_recipe()
        original = self.client.get(f"{BASE}/productos/1/receta").json()
        invalid_items = [
            {**RECIPE["detalles"][0], "cantidad": value}
            for value in ("0", "-1", "0.0000001", "NaN", "Infinity", "1000000000000")
        ] + [
            {**RECIPE["detalles"][0], "unidad": unit} for unit in ("", "g", "x" * 33)
        ] + [{**RECIPE["detalles"][0], "id_insumo": value} for value in (0, -1, 1.0, True)]
        for item in invalid_items:
            self.assertEqual(self.put_recipe({"detalles": [item]}).status_code, 422)
        self.assertEqual(self.put_recipe({"detalles": [RECIPE["detalles"][0]] * 2}).status_code, 422)
        self.assertEqual(self.put_recipe({"detalles": [], "id_restaurante": 2}).status_code, 422)
        self.assertEqual(self.client.get(f"{BASE}/productos/1/receta").json(), original)

    def test_database_failure_rolls_back_replaced_recipe(self):
        self.put_recipe()
        original = self.client.get(f"{BASE}/productos/1/receta").json()
        with patch("app.menu.service.recipe_output", side_effect=IntegrityError("private SQL", {}, Exception("internal"))):
            response = self.put_recipe({"detalles": []})
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("private", response.text)
        self.assertEqual(self.client.get(f"{BASE}/productos/1/receta").json(), original)

    def test_menu_changes_do_not_consume_stock_or_rewrite_orders(self):
        with Session(self.engine) as db:
            initial = list(db.execute(select(Insumo.id_insumo, Insumo.stock_actual).order_by(Insumo.id_insumo)))
        self.put_recipe()
        self.client.put(f"{BASE}/productos/1", headers=HEADERS, json={**PRODUCT, "activo": False})
        with Session(self.engine) as db:
            self.assertEqual(list(db.execute(select(Insumo.id_insumo, Insumo.stock_actual).order_by(Insumo.id_insumo))), initial)
            self.assertEqual(db.scalar(select(func.count()).select_from(MovimientoStock)), 0)
            self.assertEqual(len(db.get(Producto, 1).detalles_pedido), 1)

    def test_recipe_read_has_no_per_ingredient_queries(self):
        self.put_recipe()
        statements = []
        def collect(conn, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", collect)
        try:
            self.assertEqual(self.client.get(f"{BASE}/productos/1/receta").status_code, 200)
        finally:
            event.remove(self.engine, "before_cursor_execute", collect)
        self.assertLessEqual(len(statements), 3)

    def test_invalid_ids_and_missing_product(self):
        self.assertEqual(self.client.get("/api/restaurantes/0/productos").status_code, 403)
        self.assertEqual(self.client.get(f"{BASE}/productos/0/receta").status_code, 422)
        self.assertEqual(self.client.get(f"{BASE}/productos/999/receta").status_code, 404)
        self.assertEqual(self.client.delete(f"{BASE}/productos/1", headers=HEADERS).status_code, 405)


if __name__ == "__main__":
    unittest.main()
