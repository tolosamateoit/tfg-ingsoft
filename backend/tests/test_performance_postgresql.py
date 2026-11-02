"""Comparable write timings and integrity checks, exclusively on disposable PG."""
import json
import os
from pathlib import Path
import statistics
import time
import unittest

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from app.db.models import Entrega, HistorialPedido, MovimientoStock, Pedido
from tests import test_orders_postgresql, test_daily_orders
from tests.auth_support import HEADERS
from tests.test_orders import ORDER, CREATE


@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Solo PostgreSQL local descartable')
class WritePerformanceTests(unittest.TestCase):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables
    configure_client = test_daily_orders.DailyOperationTests.configure_client
    sign_in = test_daily_orders.DailyOperationTests.sign_in

    def test_write_timings_and_consistency(self):
        results = {}
        counter = [0]
        def count(*args):
            counter[0] += 1
        event.listen(self.engine, 'before_cursor_execute', count)
        self.addCleanup(event.remove, self.engine, 'before_cursor_execute', count)

        def measured(name, method, path, payload):
            counter[0] = 0
            started = time.perf_counter()
            response = getattr(self.client, method)(path, headers=HEADERS, json=payload)
            elapsed = (time.perf_counter() - started) * 1000
            self.assertIn(response.status_code, (200, 201), response.text)
            results.setdefault(name, []).append({'ms': round(elapsed, 2), 'queries': counter[0]})
            return response.json()

        for _ in range(3):
            self.sign_in(3)
            customer = measured('crear_cliente', 'post', CREATE, {k: v for k, v in ORDER.items() if k != 'correo_cliente'})
            self.assertEqual(customer['estado'], 'Nuevo')
            self.assertIsNone(customer['economia'])
            self.sign_in(1)
            created = measured('crear', 'post', CREATE, ORDER)
            oid = created['id_pedido']
            path = f'/api/restaurantes/1/pedidos/{oid}/preparacion'
            version = self.client.get(path).json()['version']
            prepared = measured('confirmar', 'put', path, {'estado': 'En preparación', 'version': version})
            ready = measured('listo', 'put', path, {'estado': 'Listo', 'version': prepared['version']})
            assigned = measured('asignar', 'post', '/api/restaurantes/1/entregas/asignar',
                                {'id_pedido': oid, 'id_repartidor': 3, 'version': ready['version']})
            self.assertEqual(len(assigned['entregas']), 1)
            delivery = assigned['entregas'][0]['id_entrega']
            path = f'/api/entregas/{delivery}/estado'
            measured('en_camino', 'put', path, {'estado': 'En camino'})
            measured('entregado', 'put', path, {'estado': 'Entregado'})
            with Session(self.engine) as db:
                self.assertEqual(db.get(Pedido, oid).estado, 'Entregado')
                self.assertEqual(db.scalar(select(func.count()).select_from(Entrega).where(Entrega.id_pedido == oid)), 1)
                self.assertEqual(db.scalar(select(func.count()).select_from(MovimientoStock).where(MovimientoStock.id_pedido == oid)), 1)
                self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido).where(
                    HistorialPedido.id_pedido == oid, HistorialPedido.estado == 'Entregado')), 1)
        summary = {name: {'median_ms': statistics.median(r['ms'] for r in samples), 'samples': samples}
                   for name, samples in results.items()}
        print('WRITE_PERFORMANCE ' + json.dumps(summary), flush=True)
        if label := os.environ.get('TFG_PERFORMANCE_LABEL'):
            folder = Path(__file__).resolve().parents[2] / '.tools' / 'performance'
            folder.mkdir(exist_ok=True)
            (folder / f'writes-{label}.json').write_text(json.dumps(summary, indent=2))
