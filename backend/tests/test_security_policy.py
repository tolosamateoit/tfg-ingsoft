"""Revocación de sesiones, compromiso y recuperación en cuentas de prueba."""
from unittest.mock import patch
import unittest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.support import router as support_router
from app.auth.models import CambioClavePendiente, Sesion
from app.auth.security import digest, verify_password
from app.db.models import Usuario
from tests import test_auth
from tests.auth_support import HEADERS, PASSWORD

class SecurityPolicyTests(unittest.TestCase):
    setUp = test_auth.AuthApiTests.setUp
    sign_in = test_auth.AuthApiTests.sign_in

    def configure_api_client(self):
        test_auth.AuthApiTests.configure_api_client(self)
        self.app.include_router(support_router, prefix='/api')
        for target in ('app.api.support.lock_email', 'app.api.auth.lock_email'):
            lock = patch(target)
            lock.start()
            self.addCleanup(lock.stop)

    def test_five_failures_revoke_all_existing_sessions_even_after_unlock(self):
        self.assertEqual(self.sign_in().status_code, 200)
        token1 = self.client.cookies.get('tfg_session')
        self.assertEqual(self.sign_in().status_code, 200)
        token2 = self.client.cookies.get('tfg_session')
        for _ in range(5):
            self.assertEqual(self.sign_in(password='incorrecta').status_code, 401)
        with Session(self.engine) as db:
            self.assertFalse(db.scalars(select(Sesion).where(Sesion.id_usuario == 1)).all())
        for token in (token1, token2):
            self.client.cookies.set('tfg_session', token)
            self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_compromise_requires_admin_reauth_restricts_session_and_rotates_password(self):
        self.assertEqual(self.sign_in(user=1).status_code, 200)
        old_session = self.client.cookies.get('tfg_session')
        self.assertEqual(self.client.post('/api/admin/cuentas/1/compromiso', headers=HEADERS,
                         json={'contrasena_administrador': PASSWORD}).status_code, 403)
        self.assertEqual(self.sign_in(user=8).status_code, 200)
        self.assertEqual(self.client.post('/api/admin/cuentas/1/compromiso', headers=HEADERS,
                         json={'contrasena_administrador': 'incorrecta'}).status_code, 401)
        response = self.client.post('/api/admin/cuentas/1/compromiso', headers=HEADERS,
                                    json={'contrasena_administrador': PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        temporary = response.json()['contrasena_temporal']
        self.assertEqual(len(temporary), 20)
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(CambioClavePendiente, 1))
            self.assertTrue(verify_password(db.get(Usuario, 1).hash_contrasena, temporary))
            self.assertFalse(db.scalars(select(Sesion).where(Sesion.id_usuario == 1)).all())
        self.client.cookies.clear()
        self.client.cookies.set('tfg_session', old_session)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.client.cookies.clear()
        self.assertEqual(self.sign_in(user=1, password=PASSWORD).status_code, 401)
        response = self.sign_in(user=1, password=temporary)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['cambio_contrasena_obligatorio'])
        self.assertEqual(self.client.get('/api/test/restaurant/1').status_code, 403)
        self.assertTrue(self.client.get('/api/auth/me').json()['cambio_contrasena_obligatorio'])
        limited = self.client.cookies.get('tfg_session')
        self.assertEqual(self.client.post('/api/auth/cambiar-contrasena', headers=HEADERS,
            json={'actual': temporary, 'nueva': temporary}).status_code, 422)
        replacement = 'Nueva frase segura 4'
        response = self.client.post('/api/auth/cambiar-contrasena', headers=HEADERS,
            json={'actual': temporary, 'nueva': replacement})
        self.assertEqual(response.status_code, 204, response.text)
        self.client.cookies.clear()
        self.client.cookies.set('tfg_session', limited)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.client.cookies.clear()
        self.assertEqual(self.sign_in(user=1, password=temporary).status_code, 401)
        self.assertEqual(self.sign_in(user=1, password=replacement).status_code, 200)
        self.assertFalse(self.client.get('/api/auth/me').json()['cambio_contrasena_obligatorio'])
        with Session(self.engine) as db:
            self.assertIsNone(db.get(CambioClavePendiente, 1))
            self.assertIsNotNone(db.scalar(select(Sesion).where(Sesion.id_usuario == 1)))

    def test_compromise_and_password_change_reject_invalid_origin_and_payload(self):
        self.sign_in(user=8)
        self.assertEqual(self.client.post('/api/admin/cuentas/1/compromiso',
            json={'contrasena_administrador': PASSWORD}).status_code, 403)
        self.assertEqual(self.client.post('/api/admin/cuentas/8/compromiso', headers=HEADERS,
            json={'contrasena_administrador': PASSWORD}).status_code, 404)
        self.assertEqual(self.client.post('/api/admin/cuentas/999/compromiso', headers=HEADERS,
            json={'contrasena_administrador': PASSWORD}).status_code, 404)
        self.assertEqual(self.client.post('/api/auth/cambiar-contrasena', headers=HEADERS,
            json={'actual': PASSWORD, 'nueva': 'muy corta'}).status_code, 422)

    def test_user_can_change_password_and_revoke_all_sessions(self):
        self.sign_in(user=3)
        old_token = self.client.cookies.get('tfg_session')
        self.sign_in(user=3)
        replacement = 'Nueva frase segura 4'
        response = self.client.post('/api/auth/cambiar-contrasena', headers=HEADERS,
            json={'actual': PASSWORD, 'nueva': replacement})
        self.assertEqual(response.status_code, 204)
        self.client.cookies.clear()
        self.client.cookies.set('tfg_session', old_token)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.client.cookies.clear()
        self.assertEqual(self.sign_in(user=3, password=PASSWORD).status_code, 401)
        self.assertEqual(self.sign_in(user=3, password=replacement).status_code, 200)

    def test_owner_can_reset_only_their_staff_and_couriers(self):
        body = {'contrasena_administrador': PASSWORD}
        self.sign_in(user=7)
        self.assertEqual(self.client.post('/api/restaurantes/2/personal/2/compromiso', headers=HEADERS, json=body).status_code, 403)
        self.assertEqual(self.client.post('/api/restaurantes/1/personal/2/compromiso', headers=HEADERS, json=body).status_code, 404)
        self.assertEqual(self.client.post('/api/restaurantes/1/personal/5/compromiso', headers=HEADERS, json=body).status_code, 404)
        self.assertEqual(self.client.post('/api/restaurantes/1/repartidores/2/compromiso', headers=HEADERS, json=body).status_code, 404)
        self.assertEqual(self.client.post('/api/restaurantes/1/personal/1/compromiso', headers=HEADERS, json=body).status_code, 200)
        self.assertEqual(self.client.post('/api/restaurantes/1/repartidores/1/compromiso', headers=HEADERS, json=body).status_code, 200)
