"""Backfill y restricciones usando las migraciones reales de PostgreSQL."""
import os
import unittest
from types import SimpleNamespace
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests import test_postgresql_constraints as support

@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Requiere PostgreSQL local descartable')
class MigrationOperatingDaysTests(unittest.TestCase):
    def test_backfill_local_dates_and_unique_per_restaurant(self):
        engine = support.local_test_engine(os.environ['TFG_TEST_POSTGRES_DSN'])
        self.addCleanup(engine.dispose)
        config = Config(str(support.BACKEND_DIR / 'alembic.ini'))
        config.cmd_opts = SimpleNamespace(x=['approved=true'])
        with engine.connect() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, '0005_disponibilidad_repartidor')
            connection.commit()
            try:
                support.seed(connection)
                connection.execute(text("UPDATE restaurante SET abierto=false"))
                connection.execute(text("UPDATE pedido SET fecha_hora='2026-01-02 02:30:00+00'"))
                connection.commit()
                command.upgrade(config, 'head')
                connection.commit()
                rows = connection.execute(text('SELECT id_restaurante, fecha FROM dia_operativo ORDER BY id_restaurante')).all()
                self.assertEqual([(r.id_restaurante, str(r.fecha)) for r in rows], [(1, '2026-01-01'), (2, '2026-01-01')])
                with self.assertRaises(IntegrityError):
                    with connection.begin_nested():
                        connection.execute(text("INSERT INTO dia_operativo VALUES (1, '2026-01-01')"))
            finally:
                connection.rollback()
                command.downgrade(config, 'base')
                connection.execute(text('DROP TABLE public.alembic_version'))
                connection.commit()
