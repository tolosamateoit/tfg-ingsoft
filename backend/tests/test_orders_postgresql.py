"""Consultas HU-03 contra el DER y las migraciones reales, solo en PostgreSQL local."""

import os
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from tests import test_orders
from tests.auth_support import HEADERS, seed
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
            for table, column, maximum in (("pedido", "id_pedido", 3), ("detalle_pedido", "id_detalle", 3),
                                           ("producto", "id_producto", 2)):
                db.execute(text(f"SELECT setval(pg_get_serial_sequence('public.{table}', '{column}'), {maximum})"))
            db.commit()
        self.configure_client()

    def drop_test_tables(self):
        with self.engine.connect() as connection:
            self.config.attributes["connection"] = connection
            command.downgrade(self.config, "base")
            connection.execute(text("DROP TABLE public.alembic_version"))
            connection.commit()

    def test_concurrent_closure_or_courier_change_is_rechecked_before_confirmation(self):
        self.sign_in(1)
        for mutation in ("UPDATE restaurante SET abierto=false WHERE id_restaurante=1",
                         "UPDATE repartidor SET estado_disponibilidad='Ocupado' WHERE id_repartidor IN (1,3)"):
            with self.subTest(mutation=mutation):
                started, finished = threading.Event(), threading.Event()
                with self.engine.connect() as first:
                    first.exec_driver_sql("UPDATE restaurante SET abierto=true WHERE id_restaurante=1")
                    first.commit()
                    first.exec_driver_sql(mutation)

                    def confirm():
                        try:
                            with TestClient(self.app) as client:
                                client.cookies.update(self.client.cookies)
                                started.set()
                                return client.post(test_orders.CREATE, headers=HEADERS, json=test_orders.ORDER)
                        finally:
                            finished.set()

                    with ThreadPoolExecutor(max_workers=1) as pool:
                        result = pool.submit(confirm)
                        self.assertTrue(started.wait(2))
                        blocked = not finished.wait(0.2)
                        first.commit()
                        response = result.result(timeout=8)
                    self.assertTrue(blocked, "La confirmación debe esperar al cambio de disponibilidad concurrente.")
                    self.assertEqual(response.status_code, 409, response.text)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM pedido").scalar_one(), 3)
