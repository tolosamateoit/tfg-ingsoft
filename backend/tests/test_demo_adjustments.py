"""Disponibilidad, reservas y asignación; únicamente fixtures descartables."""
import os
import unittest
from decimal import Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.db.models import Entrega, HistorialPedido, Insumo, Pedido, Producto, RecetaDetalle, Repartidor, Usuario
from app.logistics.service import assign_ready_orders
from tests import test_completion, test_orders_postgresql
from tests.auth_support import HEADERS
from tests.test_logistics import add_order
from tests.test_orders import ORDER

BASE = '/api/restaurantes/1'


class DemoAdjustmentsTests(unittest.TestCase):
    sign_in = test_completion.CompletionTests.sign_in
    configure_client = test_completion.CompletionTests.configure_client
    post = test_completion.CompletionTests.post
    put = test_completion.CompletionTests.put

    def setUp(self):
        test_completion.CompletionTests.setUp(self)
        self.prepare_fixture()

    def prepare_fixture(self):
        with Session(self.engine) as db:
            db.add(RecetaDetalle(id_producto=1, id_insumo=1, cantidad=1, unidad='kg'))
            db.get(Insumo, 1).stock_actual = Decimal(5)
            db.commit()
        self.sign_in(1)

    def test_menu_and_admin_availability_follow_reserved_and_physical_stock(self):
        with Session(self.engine) as db:
            # Una bebida envasada se representa mediante un insumo por unidad.
            bottle = Insumo(id_restaurante=1, nombre='Botella', unidad='unidad', stock_actual=1, costo_unitario=2)
            product = Producto(id_restaurante=1, nombre='Bebida', precio=5, costo_unitario=2, activo=True)
            no_recipe = Producto(id_restaurante=1, nombre='Sin receta', precio=5, costo_unitario=2, activo=True)
            db.add_all([bottle, product, no_recipe]); db.flush()
            db.add(RecetaDetalle(id_producto=product.id_producto, id_insumo=bottle.id_insumo, cantidad=1, unidad='unidad'))
            bottle_id, product_id, no_recipe_id = bottle.id_insumo, product.id_producto, no_recipe.id_producto
            db.commit()
        admin = {p['id_producto']: p for p in self.client.get(BASE + '/productos').json()}
        self.assertTrue(admin[product_id]['disponible_stock'])
        self.assertTrue(admin[no_recipe_id]['activo'])
        self.assertFalse(admin[no_recipe_id]['disponible_stock'])
        self.sign_in(3)
        menu = {p['id_producto']: p for p in self.client.get(BASE + '/menu').json()['productos']}
        self.assertFalse(menu[no_recipe_id]['disponible_stock'])
        body = {key: value for key, value in ORDER.items() if key != 'correo_cliente'}
        response = self.post(BASE + '/pedidos', {**body, 'detalles':[{'id_producto':product_id, 'cantidad':1}]})
        self.assertEqual(response.status_code, 201, response.text)
        menu = {p['id_producto']: p for p in self.client.get(BASE + '/menu').json()['productos']}
        self.assertFalse(menu[product_id]['disponible_stock'])
        self.assertEqual(self.post(BASE + '/pedidos', {**body, 'detalles':[{'id_producto':product_id, 'cantidad':1}]}).status_code, 409)
        self.sign_in(1)
        self.assertEqual(self.post(f'{BASE}/insumos/{bottle_id}/movimientos', {'tipo':'reposicion', 'cantidad':'1'}).status_code, 201)
        admin = {p['id_producto']: p for p in self.client.get(BASE + '/productos').json()}
        self.assertTrue(admin[product_id]['disponible_stock'])

    def test_cart_quantities_and_shared_ingredient_are_checked_together(self):
        with Session(self.engine) as db:
            extra = Producto(id_restaurante=1, nombre='Otro', precio=10, costo_unitario=1, activo=True)
            db.add(extra); db.flush()
            db.add(RecetaDetalle(id_producto=extra.id_producto, id_insumo=1, cantidad=1, unidad='kg'))
            extra_id = extra.id_producto
            db.commit()
        payload = {**ORDER, 'detalles':[{'id_producto':1, 'cantidad':3}, {'id_producto':extra_id, 'cantidad':2}]}
        self.assertEqual(self.post(BASE + '/pedidos', payload).status_code, 409)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Pedido)), 3)
            self.assertEqual(db.get(Insumo, 1).stock_actual, 5)

    def test_optional_reason_reservations_and_consumption_balances(self):
        self.assertEqual(self.post(BASE + '/insumos/1/movimientos', {'tipo':'ajuste', 'cantidad':'-5'}).status_code, 409)
        response = self.put(BASE + '/pedidos/1/preparacion', {'estado':'En preparación', 'version':0})
        self.assertEqual(response.status_code, 200, response.text)
        movement = response.json()['movimientos'][0]
        self.assertEqual(Decimal(movement['stock_antes']), 5)
        self.assertEqual(Decimal(movement['stock_despues']), 4)
        self.assertEqual(self.post(BASE + '/insumos/1/movimientos', {'tipo':'reposicion', 'cantidad':'2', 'motivo':''}).status_code, 201)
        movement = self.client.get(BASE + '/pedidos/1/preparacion').json()['movimientos'][0]
        self.assertEqual(Decimal(movement['stock_antes']), 5)
        self.assertEqual(Decimal(movement['stock_despues']), 4)

    def test_reservations_follow_preparation_cancel_and_repeat(self):
        created = self.post(BASE + '/pedidos', {**ORDER, 'detalles':[{'id_producto':1, 'cantidad':4}]})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertFalse(self.client.get(BASE + '/productos').json()[0]['disponible_stock'])
        first = self.put(BASE + '/pedidos/1/preparacion', {'estado':'En preparación', 'version':0})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.put(BASE + '/pedidos/1/preparacion', {'estado':'En preparación',
            'version':first.json()['version'], 'nueva_preparacion':True, 'motivo':'Repetir'}).status_code, 409)
        path = BASE + f"/pedidos/{created.json()['id_pedido']}/preparacion"
        version = self.client.get(path).json()['version']
        self.assertEqual(self.put(path, {'estado':'Cancelado', 'version':version}).status_code, 200)
        products = {row['id_producto']:row for row in self.client.get(BASE + '/productos').json()}
        self.assertTrue(products[1]['disponible_stock'])
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, 4)

    def test_low_stock_names_and_logical_deactivation(self):
        with Session(self.engine) as db:
            db.get(Insumo, 1).stock_actual = Decimal(1)
            name = db.get(Insumo, 1).nombre
            product_name = db.get(Producto, 1).nombre
            db.commit()
        product = next(p for p in self.client.get(BASE + '/productos').json() if p['id_producto'] == 1)
        self.assertFalse(product['disponible_stock'])
        self.assertEqual(product['insumos_faltantes'], [name])
        self.sign_in(7)
        response = self.client.delete(BASE + '/insumos/1', headers=HEADERS)
        self.assertEqual(response.status_code, 409)
        self.assertIn(product_name, response.json()['detail'])
        self.assertEqual(self.client.delete(BASE + '/productos/1', headers=HEADERS).status_code, 200)
        # El pedido nuevo todavía reserva este insumo aunque el producto haya sido retirado.
        self.assertEqual(self.client.delete(BASE + '/insumos/1', headers=HEADERS).status_code, 409)
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = 'Cancelado'
            db.commit()
        self.assertEqual(self.client.delete(BASE + '/insumos/1', headers=HEADERS).status_code, 200)
        self.assertNotIn(1, [x['id_insumo'] for x in self.client.get(BASE + '/insumos').json()])
        self.assertEqual(self.post(BASE + '/insumos/1/movimientos', {'tipo':'reposicion','cantidad':'1'}).status_code, 404)
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(RecetaDetalle, (1, 1)))
            self.assertFalse(db.get(Producto, 1).activo)
            self.assertFalse(db.get(Insumo, 1).activo)
        self.sign_in(3)
        self.assertNotIn(1, [x['id_producto'] for x in self.client.get(BASE + '/menu').json()['productos']])

    def test_staff_cannot_edit_recipes_or_deactivate(self):
        self.assertEqual(self.put(BASE + '/productos/1/receta', {'detalles':[]}).status_code, 403)
        self.assertEqual(self.client.delete(BASE + '/productos/1', headers=HEADERS).status_code, 403)
        self.assertEqual(self.client.delete(BASE + '/insumos/1', headers=HEADERS).status_code, 403)

    def test_recipe_cannot_overcommit_pending_orders(self):
        self.sign_in(7)
        response = self.put(BASE + '/productos/1/receta', {'detalles':[{'id_insumo':1, 'cantidad':'6', 'unidad':'kg'}]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get(BASE + '/productos/1/receta').json()['detalles'][0]['cantidad'], '1.000000')



@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Requiere PostgreSQL local descartable')
class DemoAdjustmentsPostgreSQLTests(DemoAdjustmentsTests):
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables

    def setUp(self):
        test_orders_postgresql.OrderReadPostgreSQLTests.setUp(self)
        with self.engine.begin() as connection:
            connection.execute(text("SELECT setval(pg_get_serial_sequence('insumo', 'id_insumo'), (SELECT max(id_insumo) FROM insumo))"))
        self.prepare_fixture()

    def test_simultaneous_orders_cannot_reserve_same_last_unit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from fastapi.testclient import TestClient
        with Session(self.engine) as db:
            db.get(Insumo, 1).stock_actual = 2  # uno está reservado por el pedido inicial
            db.commit()
        barrier = Barrier(2)
        def submit(_):
            with TestClient(self.app) as client:
                client.cookies.update(self.client.cookies)
                barrier.wait(timeout=5)
                return client.post(BASE + '/pedidos', headers=HEADERS,
                    json={**ORDER, 'detalles':[{'id_producto':1, 'cantidad':1}]}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(submit, range(2))), [201, 409])
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(Pedido)), 4)
