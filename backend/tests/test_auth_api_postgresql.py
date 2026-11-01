"""Los recorridos HTTP de HU-01 con PostgreSQL real y sin simular advisory locks."""

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth.database import get_db
from tests import test_auth
from tests.auth_support import seed
from tests.test_postgresql_constraints import local_test_engine

LOCAL_DSN = os.environ.get("TFG_TEST_POSTGRES_DSN")
BACKEND = Path(__file__).resolve().parents[1]


@unittest.skipUnless(LOCAL_DSN, "Sin PostgreSQL local descartable; no se utiliza Supabase")
class AuthApiPostgreSQLTests(test_auth.AuthApiTests):
    def setUp(self):
        self.engine = local_test_engine(LOCAL_DSN)
        self.addCleanup(self.engine.dispose)
        self.config = Config(str(BACKEND / "alembic.ini"))
        self.config.cmd_opts = SimpleNamespace(x=["approved=true"])
        with self.engine.connect() as connection:
            if inspect(connection).get_table_names(schema="public"):
                raise RuntimeError("La base local debe estar vacía; no se modificó su estructura.")
            connection.rollback()
            self.config.attributes["connection"] = connection
            command.upgrade(self.config, "head")
            connection.commit()
        self.addCleanup(self.drop_test_tables)
        with Session(self.engine) as db:
            seed(db, include_order_details=True)
        # Reutiliza todos los casos HTTP, con conexión PG real y get_db de producción.
        self.configure_api_client()
        del self.app.dependency_overrides[get_db]
        engine_override = patch("app.auth.database.get_engine", return_value=self.engine)
        engine_override.start()
        self.addCleanup(engine_override.stop)

    def drop_test_tables(self):
        with self.engine.connect() as connection:
            self.config.attributes["connection"] = connection
            command.downgrade(self.config, "base")
            connection.execute(text("DROP TABLE public.alembic_version"))
            connection.commit()

    def test_backend_owner_is_not_superuser_and_retains_crud_with_rls(self):
        with self.engine.connect() as connection:
            role = connection.execute(text(
                "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )).one()
            self.assertEqual(role[0], "postgres")
            self.assertFalse(role[1])
            self.assertFalse(role[2])
            for table in ("auth_sesion", "auth_estado_acceso"):
                ownership = connection.execute(text(
                    "SELECT pg_get_userbyid(relowner)=current_user, relrowsecurity "
                    "FROM pg_class WHERE oid=to_regclass(:table)"
                ), {"table": "public." + table}).one()
                self.assertEqual(tuple(ownership), (True, True))
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    allowed = connection.execute(text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                                                 {"table": "public." + table, "privilege": privilege}).scalar_one()
                    self.assertTrue(allowed)
        self.assertEqual(self.sign_in().status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_api_roles_have_no_table_privileges_including_truncate(self):
        with self.engine.connect() as connection:
            privileges = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]
            if int(connection.exec_driver_sql("SHOW server_version_num").scalar_one()) >= 170000:
                privileges.append("MAINTAIN")
            for role in ("anon", "authenticated", "service_role"):
                for table in ("auth_sesion", "auth_estado_acceso"):
                    for privilege in privileges:
                        allowed = connection.execute(text("SELECT has_table_privilege(:role, :table, :privilege)"),
                                                     {"role": role, "table": "public." + table,
                                                      "privilege": privilege}).scalar_one()
                        self.assertFalse(allowed, (role, table, privilege))

    def test_catalog_matches_migrations_and_denies_unprivileged_sql(self):
        with self.engine.connect() as connection:
            catalog = inspect(connection)
            self.assertEqual(len(catalog.get_table_names(schema="public")), 18)
            self.assertEqual(connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one(),
                             "0003_producto_presentacion")
            fk = catalog.get_foreign_keys("auth_sesion", schema="public")
            self.assertEqual(len(fk), 1)
            self.assertEqual(fk[0]["referred_table"], "usuario")
            self.assertEqual(fk[0]["options"], {"onupdate": "RESTRICT", "ondelete": "RESTRICT"})
            self.assertEqual(connection.execute(text(
                "SELECT count(*) FROM pg_policies WHERE schemaname='public' "
                "AND tablename IN ('auth_sesion','auth_estado_acceso')"
            )).scalar_one(), 0)
            for table in ("auth_sesion", "auth_estado_acceso"):
                public_grants = connection.execute(text(
                    "SELECT count(*) FROM pg_class c, "
                    "LATERAL aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a "
                    "WHERE c.oid=to_regclass(:table) AND a.grantee=0"
                ), {"table": "public." + table}).scalar_one()
                self.assertEqual(public_grants, 0)
                for role in ("anon", "authenticated", "service_role"):
                    for statement in (f"SELECT * FROM public.{table}", f"TRUNCATE public.{table}"):
                        with connection.begin_nested() as role_scope:
                            connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                            self.assertEqual(connection.exec_driver_sql("SELECT current_user").scalar_one(), role)
                            with self.assertRaises(DBAPIError) as failure:
                                with connection.begin_nested():
                                    connection.exec_driver_sql(statement)
                            self.assertIsInstance(failure.exception.orig, psycopg.errors.InsufficientPrivilege)
                            role_scope.rollback()
