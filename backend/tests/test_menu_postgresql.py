"""HU-02 y regresión SQL real en PostgreSQL local descartable, nunca Supabase."""

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from app.menu.demo import demo_catalog_sql

from tests import test_menu
from tests.auth_support import HEADERS, seed
from tests.menu_support import add_ingredients
from tests.test_postgresql_constraints import local_test_engine
from sqlalchemy.orm import Session

LOCAL_DSN = os.environ.get("TFG_TEST_POSTGRES_DSN")
BACKEND = Path(__file__).resolve().parents[1]


@unittest.skipUnless(LOCAL_DSN, "Sin PostgreSQL local descartable; HU-02 no usa Supabase")
class MenuPostgreSQLTests(test_menu.MenuApiTests):
    def setUp(self):
        self.engine = local_test_engine(LOCAL_DSN)
        self.addCleanup(self.engine.dispose)
        self.config = Config(str(BACKEND / "alembic.ini"))
        self.config.cmd_opts = SimpleNamespace(x=["approved=true"])
        with self.engine.connect() as connection:
            if inspect(connection).get_table_names(schema="public"):
                raise RuntimeError("Se requiere base local vacía; no se modificó su estructura.")
            connection.rollback()
            self.config.attributes["connection"] = connection
            command.upgrade(self.config, "head")
            connection.commit()
        self.addCleanup(self.drop_test_tables)
        with Session(self.engine) as db:
            seed(db, include_order_details=True)
            add_ingredients(db)
            db.execute(text("SELECT setval(pg_get_serial_sequence('public.producto','id_producto'), 2)"))
            db.execute(text("SELECT setval(pg_get_serial_sequence('public.insumo','id_insumo'), 3)"))
            db.commit()
        self.configure_client()

    def drop_test_tables(self):
        with self.engine.connect() as connection:
            self.config.attributes["connection"] = connection
            command.downgrade(self.config, "base")
            connection.execute(text("DROP TABLE public.alembic_version"))
            connection.commit()

    def test_concurrent_recipe_replacements_preserve_complete_recipe(self):
        self.assertEqual(self.put_recipe().status_code, 200)
        started, finished = threading.Event(), threading.Event()
        with self.engine.connect() as first:
            first.exec_driver_sql("SELECT pg_advisory_xact_lock(1647042, 1)")
            first.exec_driver_sql("UPDATE receta_detalle SET cantidad=2 WHERE id_producto=1")

            def second_save():
                try:
                    with TestClient(self.app) as client:
                        client.cookies.update(self.client.cookies)
                        started.set()
                        return client.put(f"{test_menu.BASE}/productos/1/receta", headers=HEADERS,
                                          json={"detalles": [{"id_insumo": 1, "cantidad": "3", "unidad": "kg"}]})
                finally:
                    finished.set()

            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(second_save)
                self.assertTrue(started.wait(2))
                self.assertFalse(finished.wait(0.2))
                first.commit()
                self.assertEqual(result.result(timeout=8).status_code, 200)
        recipe = self.client.get(f"{test_menu.BASE}/productos/1/receta").json()["detalles"]
        self.assertEqual(len(recipe), 1)
        self.assertEqual(recipe[0]["id_insumo"], 1)
        self.assertEqual(recipe[0]["cantidad"], "3.000000")

    def test_demo_catalog_sql_preserves_existing_rows_and_prevents_duplicates(self):
        with self.engine.connect() as connection:
            connection.exec_driver_sql(demo_catalog_sql(1), execution_options={"no_parameters": True})
            connection.commit()
            self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM producto WHERE id_restaurante=1").scalar_one(), 3)
            self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM insumo WHERE id_restaurante=1").scalar_one(), 5)
            self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM receta_detalle").scalar_one(), 5)
            self.assertEqual(connection.exec_driver_sql("SELECT id_restaurante FROM producto WHERE id_producto=2").scalar_one(), 2)
            connection.rollback()
            with self.assertRaises(DBAPIError):
                connection.exec_driver_sql(demo_catalog_sql(1), execution_options={"no_parameters": True})
            connection.rollback()
            self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM producto WHERE id_restaurante=1").scalar_one(), 3)
