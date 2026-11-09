"""ETAPA 5: ranking transitorio, distancias explícitas, permisos y asignaciones."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
import unittest
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.orders import router as orders_router
from app.api.couriers import router as couriers_router
from app.api.analytics import router as analytics_router
from app.api.menu import router as menu_router
from app.db.models import Entrega, HistorialPedido, Pedido, Repartidor, Usuario
from app.orders.distance import PENDING_DISTANCE
from tests import test_logistics, test_orders_postgresql
from tests.auth_support import HEADERS
from tests.test_logistics import add_order
from tests.test_orders import ORDER

BASE = '/api/restaurantes/1'
NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)


class PriorityOperationTests(unittest.TestCase):
    setUp = test_logistics.PriorityTests.setUp
    sign_in = test_logistics.PriorityTests.sign_in

    def configure_client(self):
        test_logistics.PriorityTests.configure_client(self)
        for router in (orders_router, couriers_router, analytics_router, menu_router):
            self.app.include_router(router, prefix='/api')
        if self.engine.dialect.name == 'sqlite':
            for target in ('app.orders.service.lock_order_relations', 'app.couriers.service.lock_order_relations'):
                context = patch(target); context.start(); self.addCleanup(context.stop)
        context = patch('app.logistics.priority.priority_time', return_value=NOW)
        context.start(); self.addCleanup(context.stop)

    def ranking(self):
        response = self.client.get(BASE + '/prioridades')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_new_and_preparing_orders_enter_ranking_and_positions_refresh(self):
        with Session(self.engine) as db:
            excluded = []
            for state in ('Listo', 'Asignado', 'En camino', 'Entregado', 'Cancelado', 'No entregado'):
                row = add_order(db, estado=state, importe_total=999999, fecha_hora=NOW - timedelta(days=3))
                excluded.append(row.id_pedido)
            db.commit()
        self.assertEqual([r['id_pedido'] for r in self.ranking()['pedidos']], [1])
        recalculated = self.client.post(BASE + '/prioridades', headers=HEADERS)
        self.assertEqual(recalculated.status_code, 200, recalculated.text)
        self.assertEqual([r['id_pedido'] for r in recalculated.json()['pedidos']], [1])
        with Session(self.engine) as db:
            self.assertTrue(all(db.get(Pedido, oid).puntaje_prioridad is None for oid in excluded))
            db.get(Pedido, 1).estado = 'Listo'
            db.commit()
        self.assertEqual(self.ranking()['pedidos'], [])
        with Session(self.engine) as db:
            db.get(Pedido, excluded[0]).estado = 'Nuevo'
            db.commit()
        rows = self.ranking()['pedidos']
        self.assertEqual([(r['id_pedido'], r['posicion']) for r in rows], [(excluded[0], 1)])

    def test_ready_orders_dispatch_by_priority(self):
        with Session(self.engine) as db:
            first = db.get(Pedido, 1)
            first.estado, first.fecha_hora, first.importe_total = 'Listo', NOW - timedelta(minutes=30), 999999
            second = add_order(db, estado='Listo', fecha_hora=NOW - timedelta(minutes=20))
            second_id = second.id_pedido
            for oid, minutes in ((1, 5), (second_id, 8)):
                db.add(HistorialPedido(id_pedido=oid, id_usuario=1, tipo_evento='preparacion', estado='Listo',
                                      fecha_hora=NOW - timedelta(minutes=minutes)))
            db.commit()
        self.assertEqual(self.ranking()['pedidos'], [])
        result = self.client.post(BASE + '/entregas/asignar', headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([r['id_pedido'] for r in result.json()['entregas']], [1, second_id])
        self.assertEqual(self.ranking()['pedidos'], [])

    def test_exact_consecutive_ranking_ties_factors_and_read_only(self):
        with Session(self.engine) as db:
            first = db.get(Pedido, 1)
            first.fecha_hora = NOW - timedelta(minutes=5)
            first.distancia_km = 2
            first.importe_total, first.costo_total = 2000, 1000
            a = add_order(db, estado='Nuevo', fecha_hora=NOW - timedelta(minutes=10), distancia_km=4, importe_total=3000, costo_total=1000)
            b = add_order(db, estado='Nuevo', fecha_hora=a.fecha_hora, distancia_km=4, importe_total=3000, costo_total=1000)
            ids = [a.id_pedido, b.id_pedido, first.id_pedido]
            db.commit()
            before_events = db.scalar(select(func.count()).select_from(HistorialPedido))
        rows = self.ranking()['pedidos']
        self.assertEqual([r['id_pedido'] for r in rows], ids)
        self.assertEqual([r['posicion'] for r in rows], [1, 2, 3])
        self.assertEqual([Decimal(r['puntaje_prioridad']) for r in rows], [18, 18, 14])
        self.assertEqual(rows[0]['factores_prioridad'], {'T': 10, 'D': '6.000', 'G': '2.00'})
        self.assertEqual([r['codigo'] for r in rows[0]['factores']], ['T', 'D', 'G'])
        self.assertIn('tiempo de espera', rows[0]['explicacion'])
        self.assertLessEqual(abs(sum(Decimal(f['barra']) for f in rows[0]['factores']) - 100), Decimal('.000002'))
        with Session(self.engine) as db:
            self.assertIsNone(db.get(Pedido, 1).puntaje_prioridad)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido)), before_events)
            self.assertNotIn('posicion', Pedido.__table__.columns)

    def test_each_factor_increases_real_priority_and_conditions_refresh_ranking(self):
        with Session(self.engine) as db:
            first = db.get(Pedido, 1)
            first.fecha_hora = NOW
            first.importe_total, first.costo_total, first.distancia_km = 1000, 1000, 5
            other = add_order(db, estado='Nuevo', fecha_hora=NOW, distancia_km=5, importe_total=1000, costo_total=1000)
            oid = other.id_pedido
            db.commit()
        self.assertEqual(self.ranking()['pedidos'][0]['id_pedido'], 1)
        for field, value, factor in [('fecha_hora', NOW - timedelta(minutes=10), 'T'), ('distancia_km', Decimal('1'), 'D'), ('importe_total', Decimal('20000'), 'G')]:
            with Session(self.engine) as db:
                other = db.get(Pedido, oid)
                other.fecha_hora, other.distancia_km, other.importe_total = NOW, 5, 1000
                setattr(other, field, value); db.commit()
            row = self.ranking()['pedidos'][0]
            self.assertEqual(row['id_pedido'], oid)
            self.assertEqual(row['factores'][0]['codigo'], factor)
        with Session(self.engine) as db:
            db.get(Pedido, oid).estado = 'Entregado'; db.commit()
        self.assertEqual([r['posicion'] for r in self.ranking()['pedidos']], [1])
        history = self.client.get('/api/pedidos?periodo=historial').json()['pedidos']
        self.assertEqual([r['id_pedido'] for r in history], sorted([r['id_pedido'] for r in history], reverse=True))

    def test_entered_distance_is_confirmed_and_only_edits_recalculate_it(self):
        response = self.client.post(BASE + '/pedidos', headers=HEADERS, json=ORDER)
        self.assertEqual(response.status_code, 201, response.text)
        oid = response.json()['id_pedido']
        self.assertEqual(response.json()['distancia_km'], '2.00')
        row = next(r for r in self.ranking()['pedidos'] if r['id_pedido'] == oid)
        self.assertEqual(Decimal(row['factores_prioridad']['D']), 8)
        for value in ('10.001', '-1', 'NaN'):
            self.assertEqual(self.client.put(f'{BASE}/pedidos/{oid}/distancia', headers=HEADERS, json={'distancia_km': value}).status_code, 422)
        with patch('app.logistics.service.calculate') as calculate:
            same = self.client.put(f'{BASE}/pedidos/{oid}/distancia', headers=HEADERS, json={'distancia_km': '2'})
        self.assertEqual(same.status_code, 200, same.text)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido).where(
                HistorialPedido.id_pedido == oid, HistorialPedido.tipo_evento == 'distancia')), 0)
        edited = self.client.put(f'{BASE}/pedidos/{oid}/distancia', headers=HEADERS, json={'distancia_km': '5'})
        self.assertEqual(edited.status_code, 200, edited.text)
        row = next(r for r in self.ranking()['pedidos'] if r['id_pedido'] == oid)
        self.assertEqual(Decimal(row['factores_prioridad']['D']), 5)
        with Session(self.engine) as db:
            db.get(Pedido, oid).estado = 'Listo'; db.commit()
        assignment = self.client.post(BASE + '/entregas/asignar', headers=HEADERS)
        self.assertEqual(assignment.status_code, 200, assignment.text)
        self.assertEqual(assignment.json()['entregas'][0]['id_pedido'], oid)

    def test_legacy_unverified_distances_are_not_invented(self):
        for value, status in [('10.001', 422), ('2.375', 201), ('0', 201)]:
            response = self.client.post(BASE + '/pedidos', headers=HEADERS, json={**ORDER, 'distancia_km': value})
            self.assertEqual(response.status_code, status, response.text)
        self.sign_in(3)
        payload = {k:v for k,v in ORDER.items() if k != 'correo_cliente'}
        self.assertEqual(self.client.post(BASE + '/pedidos', headers=HEADERS, json=payload).status_code, 201)
        self.sign_in(1)
        with Session(self.engine) as db:
            distance = db.get(Pedido, 1).distancia_km
            db.add(HistorialPedido(id_pedido=1, id_usuario=1, tipo_evento='registro', estado='Nuevo', detalle=PENDING_DISTANCE, fecha_hora=NOW))
            db.commit()
        row = next(r for r in self.ranking()['pedidos'] if r['id_pedido'] == 1)
        self.assertIsNone(row['distancia_km'])
        self.assertIsNone(row['factores_prioridad']['D'])
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = 'Listo'; db.commit()
        self.assertNotIn(1, [r['id_pedido'] for r in self.client.post(BASE + '/entregas/asignar', headers=HEADERS).json()['entregas']])

    def test_incompatible_assignments_and_outside_coverage_are_prevented(self):
        with Session(self.engine) as db:
            active = add_order(db, estado='Asignado')
            db.add(Entrega(id_pedido=active.id_pedido, id_repartidor=1, fecha_asignacion=NOW, estado='Asignado', costo_repartidor=0))
            db.get(Pedido, 1).estado = 'Listo'
            outside = add_order(db, distancia_km=Decimal('10.001'))
            outside_id = outside.id_pedido
            db.commit()
        self.assertEqual(self.client.put(BASE + '/repartidores/1', headers=HEADERS, json={'estado_disponibilidad':'Disponible'}).status_code, 403)
        response = self.client.post(BASE + '/entregas/asignar', headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([r['id_repartidor'] for r in response.json()['entregas']], [3])
        with Session(self.engine) as db:
            self.assertIsNone(db.scalar(select(Entrega).where(Entrega.id_pedido == outside_id)))
        self.assertEqual(self.client.post(BASE + '/entregas/asignar', headers=HEADERS).json()['entregas'], [])

    def test_roles_and_tenant_scopes_keep_everyday_staff_operations(self):
        for path in ('/prioridades', '/productos', '/productos/1/receta', '/insumos', '/stock', '/repartidores'):
            self.assertEqual(self.client.get(BASE + path).status_code, 200, path)
        for path in ('/tarifas',):
            self.assertEqual(self.client.get(BASE + path).status_code, 403, path)
        for path in ('/predicciones/diaria', '/indicadores', '/alertas'):
            self.assertEqual(self.client.get(BASE + path).status_code, 403, path)
        self.assertEqual(self.client.post(BASE + '/repartidores', headers=HEADERS, json={}).status_code, 403)
        self.assertEqual(self.client.put(BASE + '/tarifas', headers=HEADERS, json={'costo_fijo_entrega':1,'costo_por_km':2}).status_code, 403)
        self.assertEqual(self.client.get('/api/restaurantes/2/prioridades').status_code, 403)
        self.sign_in(7)
        self.assertEqual(self.client.get(BASE + '/tarifas').status_code, 200)
        self.assertEqual(self.client.get(BASE + '/predicciones/diaria').status_code, 200)
        for uid in (3, 5, 8):
            self.sign_in(uid)
            self.assertEqual(self.client.get(BASE + '/prioridades').status_code, 403)


@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Requiere PostgreSQL local descartable')
class PriorityOperationPostgreSQLTests(PriorityOperationTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables
