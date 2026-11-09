"""Regresiones de apertura, confirmación y aislamiento de personal."""
from unittest.mock import patch
import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from app.api.couriers import router as courier_router
from app.api.preparation import router as preparation_router
from app.api.logistics import router as logistics_router
from app.api.staff import router as staff_router
from app.api.menu import router as menu_router
from app.db.models import DiaOperativo, Entrega, HistorialPedido, Insumo, Pedido, Repartidor, Restaurante
from app.orders.operational_date import OPERATIONAL_ZONE
from tests.auth_support import HEADERS
import tests.test_orders as order_tests
from tests.test_orders import ORDER

class DeliveryChangesTests(unittest.TestCase):
    setUp = order_tests.OrderReadTests.setUp
    sign_in = order_tests.OrderReadTests.sign_in
    post_order = order_tests.OrderReadTests.post_order

    def configure_client(self):
        order_tests.OrderReadTests.configure_client(self)
        for router in (courier_router, preparation_router, logistics_router, staff_router, menu_router):
            self.app.include_router(router, prefix='/api')
        for target in ('app.api.couriers.lock_order_relations', 'app.preparation.service.lock_order_relations',
                       'app.api.staff.lock_email', 'app.menu.inventory.lock_recipe_relations'):
            context = patch(target)
            context.start()
            self.addCleanup(context.stop)

    def test_creation_and_confirmation_require_distinct_conditions(self):
        with Session(self.engine) as db:
            for cid in (1, 3): db.get(Repartidor, cid).estado_disponibilidad = 'No disponible'
            db.commit()
        response = self.post_order({**ORDER, 'distancia_km': '10'})
        self.assertEqual(response.status_code, 201, response.text)
        oid = response.json()['id_pedido']
        prep = f'/api/restaurantes/1/pedidos/{oid}/preparacion'
        version = self.client.get(prep).json()['version']
        failed_preparation = self.client.put(prep, headers=HEADERS, json={'estado': 'En preparación', 'version': version})
        self.assertEqual(failed_preparation.status_code, 409, failed_preparation.text)
        self.assertEqual(self.post_order({**ORDER, 'distancia_km': '10.001'}).status_code, 422)
        with Session(self.engine) as db:
            db.get(Restaurante, 1).abierto = False
            db.get(Repartidor, 3).estado_disponibilidad = 'Disponible'
            db.commit()
        self.assertEqual(self.client.put(prep, headers=HEADERS, json={'estado': 'En preparación', 'version': version}).status_code, 409)
        self.assertEqual(self.post_order().status_code, 409)

    def test_customer_can_order_without_stock_and_owner_can_confirm_after_restock(self):
        with Session(self.engine) as db:
            db.get(Insumo, 1).stock_actual = Decimal('0.1')
            db.commit()
        payload = {**ORDER, 'detalles': [{'id_producto': 1, 'cantidad': 3}]}
        payload.pop('correo_cliente')
        response = self.post_order(payload, user=3)
        self.assertEqual(response.status_code, 201, response.text)
        order_id = response.json()['id_pedido']
        self.sign_in(7)
        detail = self.client.get(f'/api/restaurantes/1/pedidos/{order_id}/preparacion').json()
        path = f'/api/restaurantes/1/pedidos/{order_id}/preparacion'
        failed = self.client.put(path, headers=HEADERS, json={'estado': 'En preparación', 'version': detail['version']})
        self.assertEqual(failed.status_code, 409, failed.text)
        self.assertIn('stock suficiente', failed.json()['detail'])
        self.assertEqual(self.client.get(f'/api/pedidos/{order_id}').json()['estado'], 'Nuevo')
        replenished = self.client.post('/api/restaurantes/1/insumos/1/movimientos', headers=HEADERS,
            json={'tipo': 'reposicion', 'cantidad': '0.2', 'motivo': 'Reposición para pedido de prueba'})
        self.assertEqual(replenished.status_code, 201, replenished.text)
        detail = self.client.get(path).json()
        confirmed = self.client.put(path, headers=HEADERS,
            json={'estado': 'En preparación', 'version': detail['version']})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, Decimal('0.0'))

    def test_owner_status_and_staff_are_restaurant_scoped(self):
        self.sign_in(7)
        self.assertEqual(self.client.put('/api/restaurantes/1/estado', headers=HEADERS, json={'abierto': False}).status_code, 200)
        self.assertEqual(self.client.get('/api/restaurantes/2/estado').status_code, 403)
        response = self.client.post('/api/restaurantes/1/personal', headers=HEADERS,
            json={'nombre': 'Empleado', 'correo': 'staff-new@test.invalid', 'contrasena': 'UnaClaveLarga2026!'})
        self.assertEqual(response.status_code, 201, response.text)
        uid = response.json()['id_usuario']
        self.assertEqual(self.client.delete(f'/api/restaurantes/2/personal/{uid}', headers=HEADERS).status_code, 403)
        self.assertEqual(self.client.delete(f'/api/restaurantes/1/personal/{uid}', headers=HEADERS).status_code, 200)
        self.sign_in(1)
        self.assertEqual(self.client.get('/api/restaurantes/1/personal').status_code, 403)

    def test_status_persists_only_open_dates_and_is_idempotent(self):
        self.sign_in(7)
        path = '/api/restaurantes/1/estado'
        initial = date(2026, 11, 1)
        with patch('app.api.couriers.local_today', return_value=initial), patch('app.orders.operating_days.local_today', return_value=initial):
            self.assertEqual(self.client.put(path, headers=HEADERS, json={'abierto': True}).status_code, 200)
            self.assertEqual(self.client.put(path, headers=HEADERS, json={'abierto': True}).status_code, 200)
        close = initial + timedelta(days=2)
        with patch('app.orders.operating_days.local_today', return_value=close):
            self.assertEqual(self.client.put(path, headers=HEADERS, json={'abierto': False}).status_code, 200)
        reopen = close + timedelta(days=4)
        with patch('app.api.couriers.local_today', return_value=reopen):
            self.assertEqual(self.client.put(path, headers=HEADERS, json={'abierto': True}).status_code, 200)
        with Session(self.engine) as db:
            rows = db.query(DiaOperativo.fecha).filter_by(id_restaurante=1).order_by(DiaOperativo.fecha).all()
            self.assertEqual([row.fecha for row in rows], [initial, initial + timedelta(days=1), close, reopen])

    def test_tracking_hides_customer_actor(self):
        with Session(self.engine) as db:
            db.add(HistorialPedido(id_pedido=1, id_usuario=1, tipo_evento='estado', estado='Nuevo', detalle='Operador privado'))
            db.commit()
        self.sign_in(3)
        response = self.client.get('/api/pedidos/1/seguimiento')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['historial'])
        self.assertTrue(all(event['usuario'] is None and event['detalle'] is None for event in response.json()['historial']))

    def test_performance_cannot_cross_restaurants(self):
        self.sign_in(7)
        self.assertEqual(self.client.get('/api/restaurantes/1/repartidores/2/desempeno').status_code, 404)
        response = self.client.get('/api/restaurantes/1/repartidores/1/desempeno')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['evolucion']), 7)

    def test_performance_uses_departure_and_delivery_events(self):
        now = datetime.now(UTC)
        with Session(self.engine) as db:
            order = db.get(Pedido, 1)
            order.fecha_hora = now
            delivery = db.get(Entrega, 1)
            delivery.fecha_asignacion = now - timedelta(minutes=40)
            delivery.estado = 'Entregado'
            delivery.costo_repartidor = 250
            db.add_all([HistorialPedido(id_pedido=1, id_usuario=5, tipo_evento='entrega', estado='En camino', fecha_hora=now - timedelta(minutes=30)),
                        HistorialPedido(id_pedido=1, id_usuario=5, tipo_evento='entrega', estado='Entregado', fecha_hora=now - timedelta(minutes=10))])
            db.commit()
        self.sign_in(5)
        response = self.client.get('/api/repartidores/me/desempeno')
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['promedio_minutos'], 20)
        self.assertEqual(result['tasa_completados'], 100)
        self.assertEqual(result['asignados'], 1)
        self.assertEqual(result['entregados'], 1)
        self.assertEqual(float(result['ganancia']), 250)

    def test_performance_ignores_final_result_on_non_operating_day(self):
        today = datetime.now(OPERATIONAL_ZONE).date()
        noon = datetime(today.year, today.month, today.day, 12, tzinfo=OPERATIONAL_ZONE)
        with Session(self.engine) as db:
            db.get(Restaurante, 1).abierto = False
            order = db.get(Pedido, 1)
            order.fecha_hora = noon
            delivery = db.get(Entrega, 1)
            delivery.estado = 'Entregado'
            delivery.fecha_asignacion = noon - timedelta(minutes=40)
            db.add_all([HistorialPedido(id_pedido=1, id_usuario=5, tipo_evento='entrega', estado='En camino', fecha_hora=noon - timedelta(minutes=30)),
                        HistorialPedido(id_pedido=1, id_usuario=5, tipo_evento='entrega', estado='Entregado', fecha_hora=noon - timedelta(minutes=10))])
            previous = Pedido(id_restaurante=1, id_cliente=1, fecha_hora=noon - timedelta(days=5), estado='No entregado',
                direccion_entrega='Prueba', medio_pago='efectivo', estado_pago='pendiente', importe_total=100, costo_total=10, distancia_km=1)
            db.add(previous); db.flush()
            db.add(Entrega(id_pedido=previous.id_pedido, id_repartidor=1, estado='No entregado',
                           fecha_asignacion=noon - timedelta(days=2), costo_repartidor=0))
            db.add(HistorialPedido(id_pedido=previous.id_pedido, id_usuario=5, tipo_evento='entrega',
                                   estado='No entregado', fecha_hora=noon - timedelta(days=1)))
            db.commit()
        self.sign_in(5)
        result = self.client.get('/api/repartidores/me/desempeno').json()
        self.assertEqual(result['promedio_minutos'], 20)
        self.assertEqual(result['tasa_completados'], 100)
