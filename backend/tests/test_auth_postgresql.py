"""Pruebas reales opt-in, solo PostgreSQL LOCAL vacío y descartable tfg_test_*.

Sin TFG_TEST_POSTGRES_DSN se omiten. Nunca leen .env ni conectan a Supabase.
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import EstadoAcceso, Sesion
from app.auth.security import digest, hash_password
from app.auth.service import as_utc, login
from app.db.models import Usuario
from tests.auth_support import PASSWORD
from tests.test_postgresql_constraints import local_test_engine

LOCAL_DSN = os.environ.get("TFG_TEST_POSTGRES_DSN")
BACKEND_DIR = Path(__file__).resolve().parents[1]


@unittest.skipUnless(LOCAL_DSN, "Sin PostgreSQL local descartable; HU-01 no se prueba contra Supabase")
class AuthPostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = local_test_engine(LOCAL_DSN)
        cls.config = Config(str(BACKEND_DIR / "alembic.ini"))
        cls.config.cmd_opts = SimpleNamespace(x=["approved=true"])
        with cls.engine.connect() as connection:
            if connection.execute(text("SELECT 1 FROM pg_tables WHERE schemaname='public' LIMIT 1")).first():
                raise RuntimeError("La base local debe estar vacía. No se modificó su estructura.")
            connection.rollback()
            cls.config.attributes["connection"] = connection
            command.upgrade(cls.config, "head")
            connection.commit()
        with Session(cls.engine) as db:
            db.add(Usuario(correo="auth@test.invalid", nombre="Sintético HU-01", rol="cliente",
                           activo=True, hash_contrasena=hash_password(PASSWORD)))
            db.commit()

    @classmethod
    def tearDownClass(cls):
        with cls.engine.connect() as connection:
            cls.config.attributes["connection"] = connection
            command.downgrade(cls.config, "base")
            connection.execute(text("DROP TABLE public.alembic_version"))
            connection.commit()
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM public.auth_sesion"))
            connection.execute(text("DELETE FROM public.auth_estado_acceso"))

    def test_parallel_failures_are_not_lost_and_persist_across_sessions(self):
        def fail(_):
            with Session(self.engine) as db:
                return login(db, "auth@test.invalid", "incorrecta")
        with ThreadPoolExecutor(max_workers=5) as executor:
            self.assertEqual(list(executor.map(fail, range(5))), [None] * 5)
        with Session(self.engine) as db:
            state = db.get(EstadoAcceso, digest("auth@test.invalid"))
            self.assertEqual(state.intentos_fallidos, 5)
            self.assertIsNotNone(state.bloqueado_hasta)
            self.assertIsNone(login(db, "auth@test.invalid", PASSWORD))

    def test_checks_fk_and_rls(self):
        now = datetime.now(UTC)
        with Session(self.engine) as db:
            user_id = db.scalar(select(Usuario.id_usuario))
            invalid = [
                EstadoAcceso(clave_correo="x" * 64, intentos_fallidos=0, actualizado_en=now),
                EstadoAcceso(clave_correo="a" * 64, intentos_fallidos=6, actualizado_en=now),
                Sesion(token_hash="b" * 64, id_usuario=user_id, creada_en=now, expira_en=now),
                Sesion(token_hash="c" * 64, id_usuario=-1, creada_en=now, expira_en=now + timedelta(hours=1)),
            ]
            for record in invalid:
                with self.assertRaises(IntegrityError):
                    with db.begin_nested():
                        db.add(record)
                        db.flush()
            rows = db.execute(text("SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('auth_sesion','auth_estado_acceso')")).all()
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(enabled for _, enabled in rows))

    def test_expiration_restarts_sequence_and_logout_token_is_persistent(self):
        now = datetime(2026, 10, 26, 12, tzinfo=UTC)
        with patch("app.auth.service.utc_now", return_value=now):
            for _ in range(5):
                with Session(self.engine) as db:
                    self.assertIsNone(login(db, "auth@test.invalid", "incorrecta"))
        with patch("app.auth.service.utc_now", return_value=now + timedelta(minutes=15)):
            with Session(self.engine) as db:
                _, token = login(db, "auth@test.invalid", PASSWORD)
        with Session(self.engine) as db:
            session = db.get(Sesion, digest(token))
            self.assertIsNotNone(session)
            self.assertEqual(as_utc(session.expira_en), now + timedelta(minutes=15, hours=8))
            db.delete(session)
            db.commit()
        with Session(self.engine) as db:
            self.assertIsNone(db.get(Sesion, digest(token)))
