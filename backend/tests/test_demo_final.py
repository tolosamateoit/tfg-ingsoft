"""Regresión del alcance final; fixtures aisladas, nunca datos reales."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import unittest
import os

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import Pedido, Producto, Insumo, Usuario, Entrega, HistorialPedido
from app.menu.service import save_recipe, update_product
from app.menu.schemas import RecipeInput, ProductInput
from app.menu.inventory import save_ingredient, IngredientInput, record_movement, MovementInput
from app.orders.service import list_orders
from tests import test_logistics, test_orders_postgresql


class FinalDemoTests(unittest.TestCase):
    setUp = test_logistics.PriorityTests.setUp
    sign_in = test_logistics.PriorityTests.sign_in

    def configure_client(self):
        test_logistics.PriorityTests.configure_client(self)
        if self.engine.dialect.name == 'sqlite':
            for target in ('app.orders.service.lock_order_relations', 'app.menu.service.lock_recipe_relations',
                           'app.menu.inventory.lock_recipe_relations'):
                p = patch(target); p.start(); self.addCleanup(p.stop)

    def test_recipe_cost_follows_ingredient_cost_and_cannot_be_overridden(self):
        with Session(self.engine) as db:
            historical = db.get(Pedido, 1).costo_total
            save_recipe(db, 1, 1, RecipeInput(detalles=[{'id_insumo':1, 'cantidad':'.2', 'unidad':'kg'}]))
            self.assertEqual(db.get(Producto, 1).costo_unitario, Decimal('200'))
            save_ingredient(db, 1, IngredientInput(nombre='Harina', unidad='kg', costo_unitario='1500'), 1)
            self.assertEqual(db.get(Producto, 1).costo_unitario, Decimal('300'))
            update_product(db, 1, 1, ProductInput(nombre='Pizza', precio='500', costo_unitario='999', activo=True))
            self.assertEqual(db.get(Producto, 1).costo_unitario, Decimal('300'))
            self.assertEqual(db.get(Pedido, 1).costo_total, historical)
            with self.assertRaises(HTTPException):
                save_recipe(db, 1, 1, RecipeInput(detalles=[{'id_insumo':3, 'cantidad':'1', 'unidad':'kg'}]))

    def test_stock_subtraction_rolls_back_and_cannot_go_negative(self):
        with Session(self.engine) as db:
            before = db.get(Insumo, 1).stock_actual
            with self.assertRaises(HTTPException):
                record_movement(db, 1, 1, MovementInput(tipo='ajuste', cantidad=-(before + 1), motivo='Prueba'), 1)
            db.rollback()
            self.assertEqual(db.get(Insumo, 1).stock_actual, before)

    def test_day_filter_paginates_and_preserves_restaurant_scope(self):
        with Session(self.engine) as db:
            actor = db.get(Usuario, 1)
            first = db.get(Pedido, 1)
            day = first.fecha_hora.date()
            page = list_orders(db, actor, 1, 0, 'historial', day)
            self.assertLessEqual(len(page.pedidos), 1)
            self.assertTrue(all(r.id_restaurante == 1 for r in page.pedidos))
            self.assertEqual(list_orders(db, actor, 20, 0, 'historial', date(2000,1,1)).total, 0)





@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Requiere PostgreSQL local descartable')
class FinalDemoPostgreSQLTests(FinalDemoTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables
