import os
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError
from sqlalchemy.pool import QueuePool
from app.core.config import DatabaseSettings
from app.db.engine import build_engine, POOL_OPTIONS
from tests.test_postgresql_constraints import local_test_engine


class PoolConfigurationTests(unittest.TestCase):
    def test_bounded_lazy_pool(self):
        settings = DatabaseSettings('example.invalid', 5432, 'test', 'test', 'secret', 'ca.crt', 5)
        with patch('psycopg.connect') as connect:
            engine = build_engine(settings)
            self.addCleanup(engine.dispose)
            connect.assert_not_called()
            self.assertIsInstance(engine.pool, QueuePool)
            self.assertEqual(engine.pool.size(), 3)
            self.assertEqual(engine.pool._max_overflow, 0)
            self.assertTrue(engine.pool._pre_ping)


@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Solo PostgreSQL local')
class PoolPostgreSQLTests(unittest.TestCase):
    def test_reuse_limit_recovery_and_transaction_cleanup(self):
        source = local_test_engine(os.environ['TFG_TEST_POSTGRES_DSN'])
        self.addCleanup(source.dispose)
        engine = create_engine(source.url, creator=source.pool._creator,
                               **{**POOL_OPTIONS, 'pool_timeout': .1})
        self.addCleanup(engine.dispose)
        with engine.connect() as conn:
            pid = conn.scalar(text('SELECT pg_backend_pid()'))
            conn.execute(text("SET LOCAL application_name='uncommitted-test'"))
        with engine.connect() as conn:
            self.assertEqual(conn.scalar(text('SELECT pg_backend_pid()')), pid)
            self.assertNotEqual(conn.scalar(text('SHOW application_name')), 'uncommitted-test')
        held = [engine.connect() for _ in range(3)]
        try:
            with self.assertRaises(TimeoutError):
                engine.connect()
        finally:
            for conn in held:
                conn.close()
        with engine.connect() as conn:
            pid = conn.scalar(text('SELECT pg_backend_pid()'))
        with source.connect() as admin:
            admin.execute(text('SELECT pg_terminate_backend(:pid)'), {'pid': pid})
            admin.commit()
        with engine.connect() as conn:
            self.assertNotEqual(conn.scalar(text('SELECT pg_backend_pid()')), pid)
        self.assertEqual(engine.pool.checkedout(), 0)
