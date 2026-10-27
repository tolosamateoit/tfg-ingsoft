"""Autenticación real por HTTP/Argon2 con persistencia SQLite; lock PG simulado."""

import os
import re
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import router
from app.auth.config import get_auth_settings
from app.auth.database import get_db
from app.auth.dependencies import COOKIE_NAME
from app.auth.models import EstadoAcceso, Sesion
from app.auth.security import digest, hash_password, normalize_email, verify_password
from app.auth.service import as_utc, lock_email
from app.db.models import Usuario
from app.main import app as production_app, private_responses, validation_error
from fastapi.exceptions import RequestValidationError
from tests.auth_support import HEADERS, ORIGIN, PASSWORD, mount_test_routes, override_database, sqlite_engine

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


class PasswordTests(unittest.TestCase):
    def test_argon2id_individual_salt_and_verification(self):
        first, second = hash_password(PASSWORD), hash_password(PASSWORD)
        self.assertTrue(first.startswith("$argon2id$"))
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(first, PASSWORD))
        self.assertFalse(verify_password(first, "otra contraseña"))

    def test_invalid_and_other_algorithm_hashes_do_not_authenticate(self):
        for encoded in (None, "test", "$argon2id$invalid", "$argon2i$invalid"):
            self.assertFalse(verify_password(encoded, PASSWORD))

    def test_password_policy_and_spaces(self):
        for password in ("corta", "x" * 21, " " * 16, "123456789012345", "PasswordPassword"):
            with self.subTest(password=password), self.assertRaises(ValueError):
                hash_password(password)
        self.assertTrue(verify_password(hash_password("  Frase segura 42 "), "  Frase segura 42 "))

    def test_email_validation_and_normalization(self):
        self.assertEqual(normalize_email(" U1@Test.Invalid "), "u1@test.invalid")
        for email in ("a", "a@b", "a b@c.invalid", "a@@b.invalid"):
            with self.assertRaises(ValueError):
                normalize_email(email)

    def test_demo_accounts_generate_sql_offline_with_individual_salts(self):
        from app.auth.accounts import demo_sql
        with patch("psycopg.connect", side_effect=AssertionError("No conectar")):
            sql = demo_sql(PASSWORD)
        hashes = re.findall(r"\$argon2id\$[^']+", sql)
        self.assertEqual(len(hashes), 9)
        self.assertEqual(len(set(hashes)), 9)
        self.assertTrue(all(verify_password(value, PASSWORD) for value in hashes))
        self.assertNotIn(PASSWORD, sql)
        self.assertIn("Ya existen cuentas sintéticas", sql)

    def test_lock_is_parameterized_and_does_not_contain_email(self):
        db = MagicMock()
        lock_email(db, digest("u1@test.invalid"))
        statement, parameters = db.execute.call_args.args
        self.assertEqual(str(statement), "SELECT pg_advisory_xact_lock(1647043, :key)")
        self.assertIsInstance(parameters["key"], int)
        self.assertNotIn("u1@", str(statement))


class AuthConfigurationTests(unittest.TestCase):
    def test_secure_default_and_local_exception(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.auth.config.ENV_FILE", Path(directory) / "missing"), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                get_auth_settings()
            for values in (
                {"AUTH_ALLOWED_ORIGINS": "http://example.invalid", "AUTH_COOKIE_SECURE": "false"},
                {"AUTH_ALLOWED_ORIGINS": "http://127.0.0.1:5173"},
                {"AUTH_ALLOWED_ORIGINS": "https://example.invalid/"},
                {"AUTH_ALLOWED_ORIGINS": "https://example.invalid:bad"},
                {"AUTH_ALLOWED_ORIGINS": "*"},
            ):
                with patch.dict(os.environ, values), self.assertRaises(ValueError):
                    get_auth_settings()
            with patch.dict(os.environ, {"AUTH_ALLOWED_ORIGINS": "https://example.invalid"}):
                self.assertTrue(get_auth_settings().cookie_secure)
            with patch.dict(os.environ, {"AUTH_ALLOWED_ORIGINS": ORIGIN, "AUTH_COOKIE_SECURE": "false"}):
                self.assertFalse(get_auth_settings().cookie_secure)
            with patch.dict(os.environ, {"AUTH_ALLOWED_ORIGINS": ORIGIN + ",http://localhost:5173", "AUTH_COOKIE_SECURE": "false"}):
                self.assertEqual(get_auth_settings().allowed_origins, frozenset({ORIGIN, "http://localhost:5173"}))


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_engine()
        self.addCleanup(self.engine.dispose)
        self.lock = patch("app.auth.service.lock_email")
        self.lock.start()
        self.addCleanup(self.lock.stop)
        self.configure_api_client()

    def configure_api_client(self):
        self.clock = patch("app.auth.service.utc_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.identity_clock = patch("app.auth.dependencies.utc_now", return_value=NOW)
        self.identity_clock.start()
        self.addCleanup(self.identity_clock.stop)
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")
        self.app.add_exception_handler(RequestValidationError, validation_error)
        self.app.middleware("http")(private_responses)
        mount_test_routes(self.app)
        override_database(self.app, self.engine)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def sign_in(self, user=1, password=PASSWORD):
        return self.client.post("/api/auth/login", headers=HEADERS,
                                json={"correo": f"u{user}@test.invalid", "contrasena": password})

    def test_login_cookie_me_and_persisted_hash_only(self):
        response = self.sign_in()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["rol"], "personal")
        cookie = response.headers["set-cookie"]
        for flag in ("HttpOnly", "SameSite=lax", "Path=/api", "Max-Age=28800"):
            self.assertIn(flag, cookie)
        token = self.client.cookies.get(COOKIE_NAME)
        self.assertEqual(len(token), 43)
        with Session(self.engine) as db:
            session = db.scalar(select(Sesion))
            self.assertEqual(session.token_hash, digest(token))
            self.assertNotEqual(session.token_hash, token)
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.headers["cache-control"], "no-store")
        self.assertNotIn("hash_contrasena", me.text)

    def test_https_cookie_uses_secure(self):
        override_database(self.app, self.engine, secure=True)
        self.assertIn("Secure", self.sign_in().headers["set-cookie"])

    def test_fifth_failure_blocks_correct_password_until_exact_expiry(self):
        for attempt in range(1, 6):
            self.assertEqual(self.sign_in(password="incorrecta").status_code, 401)
            with Session(self.engine) as db:
                state = db.get(EstadoAcceso, digest("u1@test.invalid"))
                self.assertEqual(state.intentos_fallidos, attempt)
                self.assertEqual(state.bloqueado_hasta is not None, attempt == 5)
        with patch("app.auth.service.utc_now", return_value=NOW + timedelta(minutes=14, seconds=59)):
            self.assertEqual(self.sign_in().status_code, 401)
        with Session(self.engine) as db:
            state = db.get(EstadoAcceso, digest("u1@test.invalid"))
            self.assertEqual(as_utc(state.bloqueado_hasta), NOW + timedelta(minutes=15))
        with patch("app.auth.service.utc_now", return_value=NOW + timedelta(minutes=15)):
            self.assertEqual(self.sign_in().status_code, 200)
        with Session(self.engine) as db:
            state = db.get(EstadoAcceso, digest("u1@test.invalid"))
            self.assertEqual(state.intentos_fallidos, 0)
            self.assertIsNone(state.bloqueado_hasta)

    def test_success_resets_consecutive_failures_and_lock_is_per_email(self):
        for _ in range(4):
            self.sign_in(password="incorrecta")
        self.assertEqual(self.sign_in().status_code, 200)
        self.sign_in(password="incorrecta")
        with Session(self.engine) as db:
            self.assertEqual(db.get(EstadoAcceso, digest("u1@test.invalid")).intentos_fallidos, 1)
        self.assertEqual(self.sign_in(user=2).status_code, 200)

    def test_unknown_inactive_invalid_role_and_wrong_password_share_response(self):
        expected = self.sign_in(password="incorrecta").json()
        with Session(self.engine) as db:
            db.get(Usuario, 2).activo = False
            db.get(Usuario, 7).rol = "desconocido"
            db.commit()
        for number in (99, 2, 7):
            response = self.sign_in(number)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), expected)
        for _ in range(4):
            self.sign_in(99)
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(EstadoAcceso, digest("u99@test.invalid")).bloqueado_hasta)

    def test_missing_restaurant_and_unrecognized_role_are_denied(self):
        with Session(self.engine) as db:
            db.get(Usuario, 1).id_restaurante = None
            db.commit()
        self.assertEqual(self.sign_in().status_code, 401)
        self.sign_in(7)
        with Session(self.engine) as db:
            db.get(Usuario, 7).rol = "otro"
            db.commit()
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_normalized_email_uses_same_counter_and_login_identity(self):
        self.sign_in(password="incorrecta")
        response = self.client.post("/api/auth/login", headers=HEADERS,
                                    json={"correo": " U1@TEST.INVALID ", "contrasena": PASSWORD})
        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as db:
            self.assertEqual(len(db.scalars(select(EstadoAcceso)).all()), 1)
            self.assertEqual(db.get(EstadoAcceso, digest("u1@test.invalid")).intentos_fallidos, 0)

    def test_counters_survive_new_http_client_and_session_row_reloads(self):
        self.sign_in(password="incorrecta")
        with TestClient(self.app) as another:
            another.post("/api/auth/login", headers=HEADERS,
                         json={"correo": "u1@test.invalid", "contrasena": "incorrecta"})
        with Session(self.engine) as db:
            self.assertEqual(db.get(EstadoAcceso, digest("u1@test.invalid")).intentos_fallidos, 2)

    def test_logout_revokes_token_even_when_replayed(self):
        self.sign_in()
        token = self.client.cookies.get(COOKIE_NAME)
        self.assertEqual(self.client.post("/api/auth/logout", headers=HEADERS).status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.client.cookies.set(COOKIE_NAME, token)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_missing_altered_expired_deleted_and_inactive_session(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.client.cookies.set(COOKIE_NAME, "x" * 43)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.client.cookies.clear()
        self.sign_in()
        with patch("app.auth.dependencies.utc_now", return_value=NOW + timedelta(hours=8)):
            self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        with Session(self.engine) as db:
            db.get(Usuario, 1).activo = False
            db.commit()
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_csrf_login_logout_and_future_mutations(self):
        body = {"correo": "u1@test.invalid", "contrasena": PASSWORD}
        for headers in ({}, {"Origin": ORIGIN}, {"Origin": "http://evil.invalid", "X-CSRF-Protection": "1"}):
            response = self.client.post("/api/auth/login", headers=headers, json=body)
            self.assertEqual(response.status_code, 403)
        self.sign_in()
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 403)
        self.assertEqual(self.client.post("/api/test/restaurant/1").status_code, 403)
        self.assertEqual(self.client.post("/api/test/restaurant/1", headers=HEADERS).status_code, 200)

    def test_validation_never_echoes_password_or_accepts_roles_from_client(self):
        for body in (
            {"correo": "invalid", "contrasena": PASSWORD},
            {"correo": "u1@test.invalid", "contrasena": PASSWORD, "rol": "propietario"},
            {"correo": "u1@test.invalid", "contrasena": "s" * 129},
        ):
            response = self.client.post("/api/auth/login", headers=HEADERS, json=body)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(PASSWORD, response.text)
            self.assertNotIn("s" * 129, response.text)

    def test_roles_restaurant_isolation_and_live_permission_changes(self):
        self.assertEqual(self.client.get("/api/test/restaurant/1").status_code, 401)
        for user, own, other in ((1, 1, 2), (2, 2, 1), (7, 1, 2)):
            self.sign_in(user)
            self.assertEqual(self.client.get(f"/api/test/restaurant/{own}").status_code, 200)
            self.assertEqual(self.client.get(f"/api/test/restaurant/{other}").status_code, 403)
        self.sign_in(1)
        self.assertEqual(self.client.get("/api/test/owner").status_code, 403)
        with Session(self.engine) as db:
            db.get(Usuario, 1).id_restaurante = 2
            db.commit()
        self.assertEqual(self.client.get("/api/test/restaurant/1").status_code, 403)
        self.assertEqual(self.client.get("/api/test/restaurant/2").status_code, 200)
        with Session(self.engine) as db:
            db.get(Usuario, 1).rol = "cliente"
            db.commit()
        self.assertEqual(self.client.get("/api/test/restaurant/2").status_code, 403)
        for user in (3, 5, 8):
            self.sign_in(user)
            self.assertEqual(self.client.get("/api/test/restaurant/1").status_code, 403)
        self.sign_in(7)
        self.assertEqual(self.client.get("/api/test/owner").status_code, 200)

    def test_known_order_id_cannot_cross_restaurant_or_client(self):
        self.sign_in(1)
        self.assertEqual(self.client.get("/api/test/order/1").status_code, 200)
        self.assertEqual(self.client.get("/api/test/order/2").status_code, 404)
        self.sign_in(3)
        for order in (1, 3):  # Un mismo cliente compra en restaurantes diferentes.
            self.assertEqual(self.client.get(f"/api/test/order/{order}").status_code, 200)
        self.assertEqual(self.client.get("/api/test/order/2").status_code, 404)
        self.assertEqual(self.client.get("/api/test/client/1").status_code, 200)
        self.assertEqual(self.client.get("/api/test/client/2").status_code, 404)
        self.sign_in(8)
        self.assertEqual(self.client.get("/api/test/order/1").status_code, 403)

    def test_courier_only_assigned_delivery_even_within_same_restaurant(self):
        self.sign_in(5)
        self.assertEqual(self.client.get("/api/test/delivery/1").status_code, 200)
        self.assertEqual(self.client.get("/api/test/delivery/2").status_code, 404)
        self.sign_in(9)
        self.assertEqual(self.client.get("/api/test/delivery/1").status_code, 404)
        self.sign_in(8)
        self.assertEqual(self.client.get("/api/test/delivery/1").status_code, 403)

    def test_no_operational_or_recovery_routes_are_published(self):
        paths = production_app.openapi()["paths"]
        self.assertEqual(set(paths), {"/api/health", "/api/health/database",
                                     "/api/auth/login", "/api/auth/logout", "/api/auth/me",
                                     "/api/restaurantes/{id_restaurante}/productos",
                                     "/api/restaurantes/{id_restaurante}/productos/{id_producto}",
                                     "/api/restaurantes/{id_restaurante}/insumos",
                                     "/api/restaurantes/{id_restaurante}/productos/{id_producto}/receta",
                                     "/api/restaurantes", "/api/restaurantes/{id_restaurante}/menu",
                                     "/api/restaurantes/{id_restaurante}/pedidos",
                                     "/api/pedidos", "/api/pedidos/{id_pedido}",
                                     "/api/restaurantes/{id_restaurante}/stock",
                                     "/api/restaurantes/{id_restaurante}/pedidos/{id_pedido}/preparacion",
                                     "/api/restaurantes/{id_restaurante}/repartidores",
                                     "/api/restaurantes/{id_restaurante}/repartidores/{id_repartidor}",
                                     "/api/repartidores/me",
                                     "/api/restaurantes/{id_restaurante}/prioridades",
                                     "/api/restaurantes/{id_restaurante}/entregas/asignar",
                                     "/api/restaurantes/{id_restaurante}/pedidos/{id_pedido}/distancia",
                                     "/api/pedidos/{id_pedido}/seguimiento",
                                     "/api/entregas", "/api/entregas/{id_entrega}/estado",
                                     "/api/restaurantes/{id_restaurante}/predicciones",
                                     "/api/restaurantes/{id_restaurante}/indicadores",
                                     "/api/restaurantes/{id_restaurante}/alertas",
                                     "/api/restaurantes/{id_restaurante}/dashboard",
                                     "/api/admin/diagnostico-cuenta"})


class DatabaseFailureTests(unittest.TestCase):
    def test_database_error_does_not_expose_sql_or_credentials(self):
        from sqlalchemy.exc import OperationalError
        with patch("app.auth.database.get_engine", side_effect=OperationalError("secret SQL", {}, Exception("private password"))):
            with self.assertRaises(Exception) as failure:
                next(get_db())
            self.assertEqual(failure.exception.status_code, 503)
            self.assertNotIn("private", failure.exception.detail)


if __name__ == "__main__":
    unittest.main()
