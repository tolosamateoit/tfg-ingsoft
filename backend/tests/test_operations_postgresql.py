"""HU-04/HU-05 en PostgreSQL local, reutilizando la fixture migrada de HU-03."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Insumo, MovimientoStock
from tests import test_couriers, test_preparation
from tests.auth_support import HEADERS
from tests import test_orders_postgresql as local_fixture


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class PreparationPostgreSQLTests(test_preparation.PreparationTests):
    setUp = local_fixture.OrderReadPostgreSQLTests.setUp
    drop_test_tables = local_fixture.OrderReadPostgreSQLTests.drop_test_tables

    def test_parallel_preparations_and_repeat_retries_consume_once_per_cycle(self):
        for repeat in (False, True):
            current = self.client.get(test_preparation.PREP).json()
            payload = {"estado": "En preparación", "version": current["version"],
                       "nueva_preparacion": repeat, "motivo": "Preparación arruinada" if repeat else ""}
            barrier = Barrier(2)

            def start():
                with TestClient(self.app) as client:
                    client.cookies.update(self.client.cookies)
                    barrier.wait(timeout=5)
                    return client.put(test_preparation.PREP, headers=HEADERS, json=payload).status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: start(), range(2)))
            self.assertEqual(sorted(responses), [200, 409] if repeat else [200, 200])
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, Decimal("19.6"))
            self.assertEqual(db.scalar(select(func.count()).select_from(MovimientoStock)), 4)


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class CourierPostgreSQLTests(test_couriers.CourierTests):
    setUp = local_fixture.OrderReadPostgreSQLTests.setUp
    drop_test_tables = local_fixture.OrderReadPostgreSQLTests.drop_test_tables
