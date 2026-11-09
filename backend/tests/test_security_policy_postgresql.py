"""Recorridos de seguridad contra PostgreSQL local con locks reales."""
import os
import unittest
from app.api.support import router as support_router
from tests import test_auth, test_auth_api_postgresql, test_security_policy

@unittest.skipUnless(os.environ.get('TFG_TEST_POSTGRES_DSN'), 'Requiere PostgreSQL local descartable')
class SecurityPolicyPostgreSQLTests(test_security_policy.SecurityPolicyTests):
    setUp = test_auth_api_postgresql.AuthApiPostgreSQLTests.setUp
    drop_test_tables = test_auth_api_postgresql.AuthApiPostgreSQLTests.drop_test_tables

    def configure_api_client(self):
        test_auth.AuthApiTests.configure_api_client(self)
        self.app.include_router(support_router, prefix='/api')
