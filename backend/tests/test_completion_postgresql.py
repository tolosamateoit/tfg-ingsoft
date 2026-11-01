"""Funcionalidades completadas sobre el esquema real, exclusivamente en PostgreSQL descartable."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Insumo
from tests import test_completion, test_orders_postgresql
from tests.auth_support import HEADERS


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class CompletionPostgreSQLTests(test_completion.CompletionTests):
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables

    def setUp(self):
        test_orders_postgresql.OrderReadPostgreSQLTests.setUp(self)
        with self.engine.begin() as connection:
            for table, column in (("usuario", "id_usuario"), ("repartidor", "id_repartidor"), ("insumo", "id_insumo")):
                connection.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), (SELECT max({column}) FROM {table}))"))

    def parallel_posts(self, path, payload):
        barrier = Barrier(2)
        def post():
            with TestClient(self.app) as client:
                client.cookies.update(self.client.cookies)
                barrier.wait(timeout=5)
                return client.post(path, headers=HEADERS, json=payload).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(lambda _: post(), range(2)))

    def test_concurrent_adjustments_preserve_both_movements(self):
        self.sign_in(1)
        response = self.parallel_posts(test_completion.BASE + "/insumos/1/movimientos",
                    {"tipo": "reposicion", "cantidad": "2", "motivo": "Compra"})
        self.assertEqual(response, [201, 201])
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(Insumo.stock_actual).where(Insumo.id_insumo == 1)), 24)
        self.assertEqual(len(self.client.get(test_completion.BASE + "/movimientos-stock").json()), 2)

    def test_concurrent_duplicate_courier_is_created_once(self):
        self.sign_in(7)
        self.assertEqual(sorted(self.parallel_posts(test_completion.BASE + "/repartidores", test_completion.COURIER)), [201, 409])
