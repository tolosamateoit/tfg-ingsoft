"""Verificaciones offline de la revisión inicial; nunca conectan a Supabase."""

import io
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config

from app.db.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def render_migration(*, downgrade=False):
    output = io.StringIO()
    config = Config(str(BACKEND_DIR / "alembic.ini"), output_buffer=output)
    with patch("app.db.engine.build_engine", side_effect=AssertionError("No abrir conexiones")), \
         patch("app.core.config.get_database_settings", side_effect=AssertionError("No leer secretos")), \
         patch("psycopg.connect", side_effect=AssertionError("No conectar a PostgreSQL")):
        if downgrade:
            command.downgrade(config, "0001_der_inicial:base", sql=True)
        else:
            command.upgrade(config, "0001_der_inicial", sql=True)
    return output.getvalue()


class InitialMigrationTests(unittest.TestCase):
    def test_reviewed_sql_matches_the_current_revision(self):
        snapshot = BACKEND_DIR.parent / "docs" / "sql" / "0001_der_inicial.sql"
        self.assertEqual(
            snapshot.read_text(encoding="utf-8"),
            "-- SOLO PARA REVISION. NO APLICADO A SUPABASE.\n" + render_migration(),
        )

    def test_upgrade_offline_contains_exact_der_columns(self):
        sql = render_migration()
        tables = re.findall(r"CREATE TABLE (\w+) \(\n(.*?)\n\);", sql, flags=re.DOTALL)
        self.assertEqual({name for name, _ in tables}, set(Base.metadata.tables) - {'dia_operativo'})
        for name, body in tables:
            columns = re.findall(r"^    (\w+) (?:INTEGER|TEXT|BOOLEAN|NUMERIC|DATE|TIMESTAMP|JSONB)\b", body, flags=re.MULTILINE)
            approved = {"descripcion", "imagen_url"} if name == "producto" else {"activo"} if name == "insumo" else set()
            self.assertEqual(set(columns), set(Base.metadata.tables[name].columns.keys()) - approved, name)
        self.assertIn("CREATE TABLE public.alembic_version", sql)
        self.assertIn("BEGIN;", sql)
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))

    def test_both_directions_of_integrity_and_deferred_cardinality_are_included(self):
        sql = render_migration()
        for name in ("receta", "detalle", "entrega", "movimiento", "repartidor", "historial"):
            self.assertIn(f"CREATE TRIGGER tfg_validar_{name}", sql)
        for name in ("producto", "insumo", "pedido", "usuario", "cliente", "repartidor"):
            self.assertIn(f"CREATE TRIGGER tfg_origen_{name}", sql)
        self.assertIn("pg_advisory_xact_lock", sql)
        self.assertIn("DEFERRABLE INITIALLY DEFERRED", sql)
        self.assertIn("usuario_cliente = NEW.id_usuario", sql)

    def test_no_public_data_policies_or_seed_data(self):
        sql = render_migration()
        self.assertEqual(sql.count("ENABLE ROW LEVEL SECURITY"), 16)
        self.assertNotIn("CREATE POLICY", sql)
        self.assertNotRegex(sql, r"INSERT INTO (?!public\.alembic_version)")

    def test_downgrade_removes_only_application_objects(self):
        sql = render_migration(downgrade=True)
        for name in set(Base.metadata.tables) - {'dia_operativo'}:
            self.assertIn(f"DROP TABLE public.{name};", sql)
        self.assertNotIn("CASCADE", sql)
        self.assertIn("DROP FUNCTION public.tfg_validar_relacion()", sql)


if __name__ == "__main__":
    unittest.main()
