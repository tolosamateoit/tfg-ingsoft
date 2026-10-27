"""Prioridad y seguimiento sobre el esquema existente en PostgreSQL local."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Entrega, Pedido
from tests.auth_support import HEADERS

from tests import test_logistics, test_orders_postgresql


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class PriorityPostgreSQLTests(test_logistics.PriorityTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class DeliveryPostgreSQLTests(test_logistics.DeliveryTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class AssignmentPostgreSQLTests(test_logistics.AssignmentTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables

    def test_parallel_assignment_creates_one_delivery_per_order(self):
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = "Listo"
            db.commit()
        barrier = Barrier(2)
        def assign():
            with TestClient(self.app) as client:
                client.cookies.update(self.client.cookies)
                barrier.wait(timeout=5)
                return client.post(test_logistics.BASE + "/entregas/asignar", headers=HEADERS)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: assign(), range(2)))
        self.assertTrue(all(response.status_code == 200 for response in responses), [r.text for r in responses])
        self.assertEqual(sum(len(response.json()["entregas"]) for response in responses), 1)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Entrega)), 1)
