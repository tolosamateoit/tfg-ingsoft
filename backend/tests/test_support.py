import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.support import router as support_router
from app.auth.models import EstadoAcceso
from app.auth.security import digest
from app.auth.service import utc_now
from app.db.models import Entrega, Repartidor, Usuario
from app.main import validation_error
from tests.auth_support import HEADERS, PASSWORD, override_database
from tests.menu_support import sqlite_menu_engine

PATH = "/api/admin/diagnostico-cuenta"


class SupportTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        lock = patch("app.auth.service.lock_email")
        lock.start(); self.addCleanup(lock.stop)
        self.configure_client()

    def configure_client(self):
        self.app = FastAPI()
        for router in (auth_router, support_router):
            self.app.include_router(router, prefix="/api")
        self.app.add_exception_handler(RequestValidationError, validation_error)
        override_database(self.app, self.engine)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.sign_in(8)

    def sign_in(self, user):
        self.client.cookies.clear()
        response = self.client.post("/api/auth/login", headers=HEADERS,
                                    json={"correo": f"u{user}@test.invalid", "contrasena": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)

    def diagnose(self, email="u1@test.invalid"):
        return self.client.post(PATH, headers=HEADERS, json={"correo": email})

    def test_exact_account_diagnostic_is_read_only_and_excludes_sensitive_fields(self):
        with Session(self.engine) as db:
            before = db.scalar(select(func.count()).select_from(EstadoAcceso))
        response = self.diagnose("  U1@test.invalid  ")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["correo"], "u1@test.invalid")
        self.assertEqual(response.json()["id_restaurante"], 1)
        self.assertTrue(response.json()["acceso_habilitado"])
        self.assertEqual(set(response.json()), {"id_usuario", "correo", "rol", "activo", "id_restaurante", "rol_reconocido",
                                               "pertenencia_configurada", "perfil_operativo_completo", "bloqueo_temporal", "bloqueado_hasta", "acceso_habilitado"})
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(EstadoAcceso)), before)
            self.assertTrue(db.get(Usuario, 1).activo)
        self.assertNotIn("argon2", response.text)
        self.assertNotIn("token", response.text)

    def test_blocked_and_expired_lock_are_reported_without_clearing_counters(self):
        with Session(self.engine) as db:
            db.add(EstadoAcceso(clave_correo=digest("u1@test.invalid"), intentos_fallidos=5,
                                bloqueado_hasta=utc_now() + timedelta(minutes=15), actualizado_en=utc_now()))
            db.commit()
        response = self.diagnose()
        self.assertTrue(response.json()["bloqueo_temporal"])
        self.assertFalse(response.json()["acceso_habilitado"])
        with Session(self.engine) as db:
            db.get(EstadoAcceso, digest("u1@test.invalid")).bloqueado_hasta = utc_now() - timedelta(seconds=1)
            db.commit()
        self.assertFalse(self.diagnose().json()["bloqueo_temporal"])
        with Session(self.engine) as db:
            self.assertEqual(db.get(EstadoAcceso, digest("u1@test.invalid")).intentos_fallidos, 5)

    def test_inactive_missing_restaurant_and_missing_profile_are_visible(self):
        with Session(self.engine) as db:
            db.get(Usuario, 1).activo = False
            db.get(Usuario, 7).id_restaurante = None
            db.execute(delete(Entrega).where(Entrega.id_repartidor == 1))
            db.delete(db.get(Repartidor, 1))
            db.commit()
        self.assertFalse(self.diagnose().json()["acceso_habilitado"])
        self.assertFalse(self.diagnose("u7@test.invalid").json()["pertenencia_configurada"])
        self.assertFalse(self.diagnose("u5@test.invalid").json()["perfil_operativo_completo"])
        self.assertTrue(self.diagnose("u5@test.invalid").json()["acceso_habilitado"])

    def test_non_admin_roles_csrf_unknown_account_and_invalid_input(self):
        self.assertEqual(self.diagnose("missing@test.invalid").status_code, 404)
        self.assertEqual(self.diagnose("invalid").status_code, 422)
        self.assertEqual(self.client.post(PATH, json={"correo": "u1@test.invalid"}).status_code, 403)
        self.assertEqual(self.client.post(PATH, headers=HEADERS, json={"correo": "u1@test.invalid", "rol": "propietario"}).status_code, 422)
        self.assertEqual(self.client.get("/api/admin/usuarios").status_code, 404)
        for user in (1, 3, 5, 7):
            self.sign_in(user)
            self.assertEqual(self.diagnose().status_code, 403)
