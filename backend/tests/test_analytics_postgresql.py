"""HU-08/HU-09 sobre migraciones reales; base exclusivamente local descartable."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Alerta
from tests import test_analytics, test_orders_postgresql
from tests.auth_support import HEADERS


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class ForecastPostgreSQLTests(test_analytics.ForecastTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class IndicatorPostgreSQLTests(test_analytics.IndicatorTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables

    def test_concurrent_calculation_does_not_duplicate_alerts(self):
        with Session(self.engine) as db:
            test_analytics.indicator_history(db)
        barrier = Barrier(2)
        def calculate():
            with TestClient(self.app) as client:
                client.cookies.update(self.client.cookies)
                barrier.wait(timeout=5)
                return client.post(test_analytics.BASE + "/indicadores", headers=HEADERS, json=test_analytics.PERIOD)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: calculate(), range(2)))
        self.assertTrue(all(row.status_code == 200 for row in responses), [row.text for row in responses])
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Alerta)), 4)
