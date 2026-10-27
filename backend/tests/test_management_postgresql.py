"""HU-10/HU-11 contra PostgreSQL local migrado; nunca usa Supabase."""

import os
import unittest

from tests import test_dashboard, test_support, test_orders_postgresql


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class DashboardPostgreSQLTests(test_dashboard.DashboardTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class SupportPostgreSQLTests(test_support.SupportTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables
