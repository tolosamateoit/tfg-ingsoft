"""Pedidos del día y acciones rápidas sobre los servicios reales."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
import unittest

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.db.models import Entrega, HistorialPedido, Insumo, MovimientoStock, Pedido, Restaurante
from app.orders.distance import PENDING_DISTANCE
from tests.auth_support import HEADERS
from tests.test_logistics import add_order
from tests.test_orders import ORDER
from tests import test_priority_operation, test_orders_postgresql

BASE = '/api/restaurantes/1'
STAMP = datetime(2026, 10, 31, 15, tzinfo=UTC)


class DailyOperationTests(unittest.TestCase):
    setUp = test_priority_operation.PriorityOperationTests.setUp
    sign_in = test_priority_operation.PriorityOperationTests.sign_in

    def configure_client(self):
        test_priority_operation.PriorityOperationTests.configure_client(self)
        with Session(self.engine) as db:
            db.get(Pedido, 1).fecha_hora = STAMP
            db.commit()

    def day(self, query=''):
        response = self.client.get(BASE + '/pedidos/operacion' + query)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def prepare(self, state, version):
        return self.client.put(BASE + '/pedidos/1/preparacion', headers=HEADERS, json={'estado': state, 'version': version})

    def assign(self, oid, courier, version, **extra):
        return self.client.post(BASE + '/entregas/asignar', headers=HEADERS, json={
            'id_pedido': oid, 'id_repartidor': courier, 'version': version, **extra})

    def test_day_groups_ranking_pagination_and_history(self):
        with Session(self.engine) as db:
            preparing = add_order(db, estado='En preparación', fecha_hora=STAMP - timedelta(hours=1), importe_total=20000)
            ready = add_order(db, estado='Listo', fecha_hora=STAMP)
            route = add_order(db, estado='En camino', fecha_hora=STAMP)
            add_order(db, estado='Entregado', fecha_hora=STAMP)
            add_order(db, estado='Cancelado', fecha_hora=STAMP)
            old = add_order(db, estado='Nuevo', fecha_hora=STAMP - timedelta(days=1))
            db.add(Entrega(id_pedido=route.id_pedido, id_repartidor=1, fecha_asignacion=STAMP, estado='En camino', costo_repartidor=0))
            preparing_id, ready_id, route_id, old_id = preparing.id_pedido, ready.id_pedido, route.id_pedido, old.id_pedido
            db.commit()
        data = self.day('?limit=1')
        self.assertEqual(data['fecha_operativa'], '2026-10-31')
        self.assertEqual([r['id_pedido'] for r in data['activos']], [preparing_id, 1])
        self.assertEqual([r['prioridad']['posicion'] for r in data['activos']], [1, 2])
        self.assertEqual([r['id_pedido'] for r in data['listos']], [ready_id])
        self.assertIsNone(data['listos'][0]['prioridad'])
        self.assertEqual(data['en_entrega'][0]['id_pedido'], route_id)
        self.assertIsNotNone(data['en_entrega'][0]['repartidor'])
        self.assertEqual([c['id_repartidor'] for c in data['repartidores']], [3])
        self.assertEqual(data['total_finalizados'], 2)
        self.assertNotEqual(self.day('?limit=1&offset=1')['finalizados'][0]['id_pedido'], data['finalizados'][0]['id_pedido'])
        history = self.client.get('/api/pedidos?periodo=historial&limit=100').json()['pedidos']
        self.assertIn(old_id, [r['id_pedido'] for r in history])
        self.assertTrue(all('prioridad' not in r for r in history))
        self.assertEqual(history, sorted(history, key=lambda r: (r['fecha_hora'], r['id_pedido']), reverse=True))

    def test_confirm_ready_selected_courier_and_finish_without_duplicates(self):
        row = self.day()['activos'][0]
        first = self.prepare('En preparación', row['version'])
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.prepare('En preparación', row['version']).status_code, 200)
        preparing = self.day()['activos'][0]
        self.assertEqual(preparing['estado'], 'En preparación')
        self.assertEqual(preparing['prioridad']['posicion'], 1)
        self.assertEqual(self.prepare('Listo', row['version']).status_code, 409)
        self.assertEqual(self.prepare('Listo', preparing['version']).status_code, 200)
        data = self.day()
        self.assertEqual(data['activos'], [])
        assigned = self.assign(1, 3, data['listos'][0]['version'])
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()['entregas'][0]['id_repartidor'], 3)
        self.assertEqual(self.assign(1, 1, data['listos'][0]['version']).status_code, 409)
        row = self.day()['en_entrega'][0]
        self.assertEqual(row['id_repartidor'], 3)
        self.assertNotIn(3, [r['id_repartidor'] for r in self.day()['repartidores']])
        path = f"/api/entregas/{row['id_entrega']}/estado"
        for state in ('En camino', 'Entregado', 'Entregado'):
            response = self.client.put(path, headers=HEADERS, json={'estado': state})
            self.assertEqual(response.status_code, 200, response.text)
        data = self.day()
        self.assertEqual(data['en_entrega'], [])
        self.assertEqual(data['finalizados'][0]['estado'], 'Entregado')
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(MovimientoStock).where(MovimientoStock.id_pedido == 1)), 1)
            self.assertEqual(db.get(Insumo, 1).stock_actual, Decimal('19.8'))
            self.assertEqual(db.scalar(select(func.count()).select_from(Entrega).where(Entrega.id_pedido == 1)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido).where(
                HistorialPedido.id_pedido == 1, HistorialPedido.estado == 'Entregado')), 1)

    def test_rejection_preserves_history_without_stock_consumption(self):
        version = self.day()['activos'][0]['version']
        first = self.prepare('Cancelado', version)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.prepare('Cancelado', version).status_code, 200)
        self.assertEqual(self.prepare('En preparación', first.json()['version']).status_code, 409)
        data = self.day()
        self.assertEqual(data['activos'], [])
        self.assertEqual(data['finalizados'][0]['estado'], 'Cancelado')
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, 20)
            self.assertEqual(db.scalar(select(func.count()).select_from(MovimientoStock)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido).where(HistorialPedido.id_pedido == 1)), 1)

    def test_invalid_states_versions_busy_foreign_couriers_and_permissions(self):
        self.assertEqual(self.assign(1, 1, 0).status_code, 409)
        response = self.prepare('En preparación', 0)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.prepare('Cancelado', response.json()['version']).status_code, 409)
        self.prepare('Listo', response.json()['version'])
        row = self.day()['listos'][0]
        self.assertEqual(self.assign(1, 1, row['version'] + 1).status_code, 409)
        self.assertEqual(self.assign(1, 2, row['version']).status_code, 409)
        with Session(self.engine) as db:
            other = add_order(db, estado='En camino', fecha_hora=STAMP)
            db.add(Entrega(id_pedido=other.id_pedido, id_repartidor=1, fecha_asignacion=STAMP, estado='En camino', costo_repartidor=0))
            db.commit()
        self.assertEqual(self.assign(1, 1, row['version']).status_code, 409)
        self.assertEqual(self.assign(2, 3, 0).status_code, 404)
        self.assertEqual(self.client.get('/api/restaurantes/2/pedidos/operacion').status_code, 403)
        for user in (3, 5, 8):
            self.sign_in(user)
            self.assertEqual(self.client.get(BASE + '/pedidos/operacion').status_code, 403)
            self.assertEqual(self.prepare('Cancelado', 0).status_code, 403)
            self.assertEqual(self.assign(1, 3, row['version']).status_code, 403)

    def test_unknown_distance_is_omitted_and_only_real_input_enables_dispatch(self):
        with Session(self.engine) as db:
            db.add(HistorialPedido(id_pedido=1, id_usuario=1, tipo_evento='registro', estado='Nuevo', fecha_hora=STAMP, detalle=PENDING_DISTANCE))
            db.get(Restaurante, 1).costo_fijo_entrega = 5
            db.get(Restaurante, 1).costo_por_km = 1
            db.commit()
        row = self.day()['activos'][0]
        self.assertIsNone(row['distancia_km'])
        self.assertIsNone(row['prioridad']['factores_prioridad']['D'])
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = 'Listo'
            db.commit()
        row = self.day()['listos'][0]
        self.assertEqual(self.assign(1, 3, row['version']).status_code, 409)
        response = self.assign(1, 3, row['version'], distancia_km='2')
        self.assertEqual(response.status_code, 200, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Pedido, 1).distancia_km, 2)
            self.assertEqual(db.scalar(select(Entrega.costo_repartidor).where(Entrega.id_pedido == 1)), 7)

    def test_new_order_appears_immediately_with_consecutive_positions(self):
        response = self.client.post(BASE + '/pedidos', headers=HEADERS, json=ORDER)
        self.assertEqual(response.status_code, 201, response.text)
        data = self.day()
        self.assertIn(response.json()['id_pedido'], [r['id_pedido'] for r in data['activos']])
        self.assertEqual([r['prioridad']['posicion'] for r in data['activos']], list(range(1, len(data['activos']) + 1)))
        self.assertTrue(all(r['estado'] in {'Nuevo', 'En preparación'} for r in data['activos']))


@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Requiere PostgreSQL local descartable')
class DailyOperationPostgreSQLTests(DailyOperationTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables

    def test_two_orders_cannot_take_the_same_courier_concurrently(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from fastapi.testclient import TestClient
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = 'Listo'
            second = add_order(db, estado='Listo', fecha_hora=STAMP)
            second_id = second.id_pedido
            db.commit()
        barrier = Barrier(2)
        def assign(oid):
            with TestClient(self.app) as client:
                client.cookies.update(self.client.cookies)
                barrier.wait(timeout=5)
                return client.post(BASE + '/entregas/asignar', headers=HEADERS,
                    json={'id_pedido': oid, 'id_repartidor': 3, 'version': 0}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(assign, [1, second_id]))
        self.assertEqual(sorted(statuses), [200, 409])
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Entrega).where(Entrega.id_repartidor == 3)), 1)
