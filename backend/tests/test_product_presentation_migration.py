"""SQL revisable para la única extensión del modelo autorizada en esta etapa."""

import io
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[1]


def render_presentation_migration():
    output = io.StringIO()
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=output)
    with patch("app.db.engine.build_engine", side_effect=AssertionError("No conectar")):
        command.upgrade(config, "0002_hu01_auth:0003_producto_presentacion", sql=True)
    return output.getvalue()


class PresentationMigrationTests(unittest.TestCase):
    def test_only_two_nullable_columns_without_data_mutation_or_new_tables(self):
        sql = render_presentation_migration()
        self.assertIn("ALTER TABLE public.producto ADD COLUMN descripcion TEXT", sql)
        self.assertIn("ALTER TABLE public.producto ADD COLUMN imagen_url TEXT", sql)
        self.assertNotIn("NOT NULL", sql)
        self.assertNotIn("CREATE TABLE", sql)
        self.assertNotIn("DELETE FROM", sql)
        self.assertEqual((BACKEND.parent / "docs/sql/0003_producto_presentacion.sql").read_text(encoding="utf-8"),
                         "-- SOLO PARA REVISION. NO APLICADO A SUPABASE.\n" + sql)
