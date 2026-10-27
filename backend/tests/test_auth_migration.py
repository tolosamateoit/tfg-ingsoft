"""SQL offline de HU-01: no lee secretos ni conecta a PostgreSQL."""

import io
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable

from app.auth.models import AuthBase
from app.db.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]
SQL_HEADER = "-- HU-01: SOLO PARA REVISION. NO APLICADO A SUPABASE.\n"


def render_auth_migration(downgrade=False):
    output = io.StringIO()
    config = Config(str(BACKEND_DIR / "alembic.ini"), output_buffer=output)
    with patch("app.db.engine.build_engine", side_effect=AssertionError("No conectar")), \
         patch("app.core.config.get_database_settings", side_effect=AssertionError("No leer secretos")), \
         patch("psycopg.connect", side_effect=AssertionError("No conectar")):
        if downgrade:
            command.downgrade(config, "0002_hu01_auth:0001_der_inicial", sql=True)
        else:
            command.upgrade(config, "0001_der_inicial:0002_hu01_auth", sql=True)
    return output.getvalue()


class AuthMigrationTests(unittest.TestCase):
    def test_sql_snapshot_matches_revision(self):
        expected = BACKEND_DIR.parent / "docs/sql/0002_hu01_auth.sql"
        self.assertEqual(expected.read_text(encoding="utf-8"), SQL_HEADER + render_auth_migration())

    def test_only_two_technical_tables_with_checks_fk_rls_and_no_business_changes(self):
        sql = render_auth_migration()
        self.assertEqual(sql.count("CREATE TABLE"), 2)
        self.assertIn("intentos_fallidos BETWEEN 0 AND 5", sql)
        self.assertEqual(sql.count("~ '^[0-9a-f]{64}$'"), 2)
        self.assertIn("expira_en > creada_en", sql)
        self.assertIn("REFERENCES public.usuario (id_usuario) ON DELETE RESTRICT ON UPDATE RESTRICT", sql)
        self.assertEqual(sql.count("ENABLE ROW LEVEL SECURITY"), 2)
        self.assertEqual(sql.count("REVOKE ALL ON TABLE"), 2)
        self.assertNotIn("CREATE POLICY", sql)
        self.assertNotIn("ALTER TABLE public.usuario", sql)
        self.assertNotIn("INSERT INTO usuario", sql)
        self.assertIn("BEGIN;", sql)
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))

    def test_technical_metadata_is_separate_and_fk_resolves(self):
        self.assertEqual(set(AuthBase.metadata.tables), {"auth_estado_acceso", "auth_sesion"})
        self.assertEqual(len(Base.metadata.tables), 15)
        for table in AuthBase.metadata.sorted_tables:
            self.assertIn("CREATE TABLE", str(CreateTable(table).compile(dialect=dialect())))
        fk = next(iter(AuthBase.metadata.tables["auth_sesion"].foreign_keys))
        self.assertIs(fk.column, Base.metadata.tables["usuario"].c.id_usuario)
        self.assertEqual(fk.ondelete, "RESTRICT")

    def test_downgrade_removes_only_technical_tables(self):
        sql = render_auth_migration(downgrade=True)
        self.assertEqual(sql.count("DROP TABLE"), 2)
        self.assertNotIn("DROP TABLE public.usuario", sql)
        self.assertNotIn("CASCADE", sql)
