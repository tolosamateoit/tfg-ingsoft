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
from app.demo_history.simulation import advance, delay, local_demo
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

    def test_simulation_manual_changes_and_payment_are_idempotent(self):
        with Session(self.engine, expire_on_commit=False) as db:
            self.assertEqual(advance(db, 1), 'En preparación')
            self.assertEqual(advance(db, 1), 'Listo')
            # Marcar como nuevo simulado; la asignación ignora los históricos.
            db.add(HistorialPedido(id_pedido=1, id_usuario=1, tipo_evento='registro', estado='Nuevo', detalle='[demo_simulacion]'))
            db.commit()
            self.assertEqual(advance(db, 1), 'Asignado')
            self.assertEqual(advance(db, 1), 'En camino')
            self.assertEqual(advance(db, 1), 'Entregado')
            count = db.scalar(select(func.count()).select_from(HistorialPedido))
            self.assertIsNone(advance(db, 1))
            self.assertEqual(db.get(Pedido, 1).estado_pago, 'pagado')
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido)), count)
            self.assertEqual(db.scalar(select(func.count()).select_from(Entrega)), 1)

    def test_simulation_dispatch_does_not_touch_historical_ready_orders(self):
        from app.logistics.service import assign_ready_orders
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = 'Listo'; db.commit()
            result = assign_ready_orders(db, db.get(Usuario, 1), 1, demo_only=True)
            self.assertEqual(result.entregas, [])
            self.assertEqual(db.get(Pedido, 1).estado, 'Listo')

    def test_local_scope_and_bounded_delays(self):
        from app.auth.config import AuthSettings
        with patch('app.demo_history.simulation.get_auth_settings', return_value=AuthSettings(frozenset(), True)):
            self.assertFalse(local_demo())
        for oid in range(100):
            self.assertTrue(15 <= delay(oid, 'Nuevo') <= 25)

    def test_worker_runs_without_browser_and_keeps_history_untouched(self):
        if self.engine.dialect.name != 'postgresql':
            self.skipTest('El lock del worker requiere PostgreSQL')
        from app.demo_history.simulation import run_once
        with Session(self.engine) as db:
            db.add(HistorialPedido(id_pedido=1, id_usuario=1, tipo_evento='registro', estado='Nuevo', detalle='[demo_simulacion]'))
            db.commit()
        class Clock:
            ticks = 0
            def is_set(self): return self.ticks >= 80
            def wait(self, seconds): self.ticks += seconds; return self.is_set()
        clock = Clock()
        with patch('app.demo_history.simulation.get_engine', return_value=self.engine), \
             patch('app.demo_history.simulation.monotonic', side_effect=lambda: clock.ticks), \
             patch('app.demo_history.simulation.delay', return_value=2):
            run_once(clock)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Pedido, 1).estado, 'Entregado')
            self.assertEqual(db.get(Pedido, 1).estado_pago, 'pagado')
            self.assertEqual(db.get(Pedido, 2).estado, 'Nuevo')


@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Requiere PostgreSQL local descartable')
class FinalDemoPostgreSQLTests(FinalDemoTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables
