"""Consultas HU-03 contra el DER y las migraciones reales, solo en PostgreSQL local."""

import os
import unittest
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from tests import test_orders
from tests.auth_support import seed
from tests.menu_support import add_ingredients
from tests.test_postgresql_constraints import local_test_engine

LOCAL_DSN = os.environ.get("TFG_TEST_POSTGRES_DSN")
BACKEND = Path(__file__).resolve().parents[1]


@unittest.skipUnless(LOCAL_DSN, "Requiere PostgreSQL local descartable; nunca Supabase")
class OrderReadPostgreSQLTests(test_orders.OrderReadTests):
    def setUp(self):
        self.engine = local_test_engine(LOCAL_DSN)
        self.addCleanup(self.engine.dispose)
        self.config = Config(str(BACKEND / "alembic.ini"))
        self.config.cmd_opts = SimpleNamespace(x=["approved=true"])
        with self.engine.connect() as connection:
            if inspect(connection).get_table_names(schema="public"):
                raise RuntimeError("Se requiere una base local vacía.")
            connection.rollback()
            self.config.attributes["connection"] = connection
            command.upgrade(self.config, "head")
            connection.commit()
        self.addCleanup(self.drop_test_tables)
        with Session(self.engine) as db:
            seed(db, include_order_details=True)
            add_ingredients(db)
            db.commit()
        self.configure_client()

    def drop_test_tables(self):
        with self.engine.connect() as connection:
            self.config.attributes["connection"] = connection
            command.downgrade(self.config, "base")
            connection.execute(text("DROP TABLE public.alembic_version"))
            connection.commit()
