"""Varias pestañas con el mismo cookie jar: selección, revocación y expiración."""

from datetime import timedelta
import os
import unittest

from sqlalchemy.orm import Session

from app.auth.dependencies import COOKIE_NAME
from app.auth.models import Sesion
from app.auth.security import digest
from tests import test_auth, test_auth_api_postgresql
from tests.auth_support import HEADERS, PASSWORD

A = "a" * 32
B = "b" * 32


class TabSessionTests(unittest.TestCase):
    setUp = test_auth.AuthApiTests.setUp
    configure_api_client = test_auth.AuthApiTests.configure_api_client
    sign_in = test_auth.AuthApiTests.sign_in

    def tab_login(self, tab, user):
        return self.client.post("/api/auth/login", headers={**HEADERS, "X-Oliva-Tab": tab},
                                json={"correo": f"u{user}@test.invalid", "contrasena": PASSWORD})

    def me(self, tab):
        return self.client.get("/api/auth/me", headers={"X-Oliva-Tab": tab})

    def test_shared_cookies_keep_independent_roles_and_logout_revokes_only_one(self):
        owner = self.tab_login(A, 7)
        self.assertEqual(owner.status_code, 200, owner.text)
        for flag in ("HttpOnly", "SameSite=lax", "Path=/api", "Max-Age=28800"):
            self.assertIn(flag, owner.headers["set-cookie"])
        self.assertNotIn("token", owner.json())
        token_a = self.client.cookies.get(f"{COOKIE_NAME}_{A}")
        self.assertEqual(self.tab_login(B, 3).status_code, 200)
        self.assertEqual(self.me(A).json()["rol"], "propietario")
        self.assertEqual(self.me(B).json()["rol"], "cliente")
        # Navegaciones y recargas reenvían el mismo identificador de pestaña.
        for _ in range(2):
            self.assertEqual(self.me(A).json()["rol"], "propietario")
        response = self.client.post("/api/auth/logout", headers={**HEADERS, "X-Oliva-Tab": A})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.me(A).status_code, 401)
        self.assertEqual(self.me(B).json()["rol"], "cliente")
        self.client.cookies.set(f"{COOKIE_NAME}_{A}", token_a, path="/api")
        self.assertEqual(self.me(A).status_code, 401)
        with Session(self.engine) as db:
            self.assertIsNone(db.get(Sesion, digest(token_a)))

    def test_one_tab_expiration_and_invalid_or_new_tab_never_fall_back_to_cookie(self):
        self.sign_in(1)  # Cookie de compatibilidad compartida: no debe adoptarse.
        self.tab_login(A, 7); self.tab_login(B, 5)
        token_a = self.client.cookies.get(f"{COOKIE_NAME}_{A}")
        with Session(self.engine) as db:
            session = db.get(Sesion, digest(token_a))
            session.creada_en = test_auth.NOW - timedelta(hours=9)
            session.expira_en = test_auth.NOW - timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.me(A).status_code, 401)
        self.assertEqual(self.me(B).json()["rol"], "repartidor")
        for invalid in ("", "c" * 32, "g" * 32, "a" * 31, "../../cookie"):
            self.assertEqual(self.me(invalid).status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").json()["rol"], "personal")
        self.assertEqual(self.client.post("/api/auth/logout", headers={"X-Oliva-Tab": B}).status_code, 403)
        self.assertEqual(self.me(B).status_code, 200)


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Solo PostgreSQL local descartable")
class TabSessionPostgreSQLTests(TabSessionTests):
    setUp = test_auth_api_postgresql.AuthApiPostgreSQLTests.setUp
    drop_test_tables = test_auth_api_postgresql.AuthApiPostgreSQLTests.drop_test_tables
