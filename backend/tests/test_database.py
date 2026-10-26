"""Pruebas sin credenciales ni conexiones reales: python -m unittest discover -s tests."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg
from fastapi import HTTPException

from app.api.health import database_health, health
from app.core.config import DatabaseConfigurationError, DatabaseSettings, get_database_settings
from app.db.connection import check_database_connection


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "ca.crt").write_text("test certificate", encoding="utf-8")
        self.env_file = self.root / ".env"
        self.env_file.write_text(
            "PGHOST=example.invalid\nPGUSER=test-user\nPGDATABASE=postgres\n"
            "PGPASSWORD='a ${literal} # secret'\nPGSSLROOTCERT=ca.crt\n",
            encoding="utf-8",
        )
        for context in (
            patch.dict(os.environ, {}, clear=True),
            patch("app.core.config.BACKEND_DIR", self.root),
            patch("app.core.config.ENV_FILE", self.env_file),
        ):
            context.start()
            self.addCleanup(context.stop)

    def test_loads_env_preserves_password_and_resolves_certificate(self):
        settings = get_database_settings()
        self.assertEqual(settings.password, "a ${literal} # secret")
        self.assertNotIn(settings.password, repr(settings))
        self.assertEqual(settings.sslrootcert, str((self.root / "ca.crt").resolve()))

    def test_process_environment_takes_precedence(self):
        with patch.dict(os.environ, {"PGUSER": "environment-user"}):
            self.assertEqual(get_database_settings().user, "environment-user")

    def test_missing_configuration_does_not_attempt_connection(self):
        with patch.dict(os.environ, {"PGPASSWORD": ""}), patch("app.db.connection.psycopg.connect") as connect:
            with self.assertRaises(DatabaseConfigurationError):
                check_database_connection()
            connect.assert_not_called()

    def test_rejects_invalid_ports_timeouts_and_unverified_tls(self):
        for overrides in (
            {"PGPORT": "not-a-port"}, {"PGPORT": "0"}, {"PGPORT": "65536"},
            {"PGCONNECT_TIMEOUT": "0"}, {"PGCONNECT_TIMEOUT": "31"},
            {"PGSSLMODE": "disable"}, {"PGSSLMODE": "require"},
            {"PGSSLROOTCERT": "missing.crt"},
        ):
            with self.subTest(overrides=overrides), patch.dict(os.environ, overrides):
                with self.assertRaises(DatabaseConfigurationError):
                    get_database_settings()


class ConnectionTests(unittest.TestCase):
    @patch("app.db.connection.psycopg.connect")
    @patch("app.db.connection.get_database_settings")
    def test_driver_error_is_logged_sanitized_and_propagated(self, settings, connect):
        settings.return_value = DatabaseSettings(
            host="private.example.invalid", port=5432, dbname="private-db",
            user="private-user", password="private secret@123", sslrootcert="C:/private/ca.crt",
            connect_timeout=5,
        )
        error = psycopg.OperationalError(
            'connection to server at "203.0.113.10" failed: '
            'FATAL: password authentication failed for user "private-user"; '
            "host=private.example.invalid password=private secret@123 "
            "encoded=private%20secret%40123 plus=private+secret%40123 "
            "database=private-db certificate=C:/private/ca.crt"
        )
        connect.side_effect = error
        with self.assertLogs("uvicorn.error", level="ERROR") as captured:
            with self.assertRaises(psycopg.OperationalError):
                check_database_connection()
        output = "\n".join(captured.output)
        self.assertIn("password authentication failed", output)
        for value in ("203.0.113.10", "private", "Traceback"):
            self.assertNotIn(value, output)

    @patch("app.db.connection.psycopg.connect")
    @patch("app.db.connection.get_database_settings")
    def test_read_only_select_and_connection_cleanup(self, settings, connect):
        settings.return_value = MagicMock(connect_timeout=5)
        connection = connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (1,)
        self.assertTrue(check_database_connection())
        cursor.execute.assert_called_once_with("SELECT 1")
        self.assertEqual(connect.call_args.kwargs["sslmode"], "verify-full")
        self.assertIn("default_transaction_read_only=on", connect.call_args.kwargs["options"])
        self.assertIn("statement_timeout=5000", connect.call_args.kwargs["options"])
        connection.cursor.return_value.__exit__.assert_called_once()
        connect.return_value.__exit__.assert_called_once()

    @patch("app.db.connection.psycopg.connect")
    @patch("app.db.connection.get_database_settings")
    def test_unexpected_result_is_not_success(self, settings, connect):
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        self.assertFalse(check_database_connection())


class HealthTests(unittest.TestCase):
    def test_basic_health_does_not_need_database(self):
        self.assertEqual(health().status, "ok")

    @patch("app.api.health.check_database_connection", return_value=True)
    def test_database_success(self, check):
        self.assertEqual(database_health().status, "ok")
        check.assert_called_once()

    def test_failure_is_503_without_sensitive_driver_details(self):
        for outcome in (
            DatabaseConfigurationError("private configuration"),
            psycopg.OperationalError("private password and host"),
            False,
        ):
            kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
            with self.subTest(outcome=type(outcome).__name__), patch("app.api.health.check_database_connection", **kwargs):
                with self.assertRaises(HTTPException) as raised:
                    database_health()
                self.assertEqual(raised.exception.status_code, 503)
                self.assertNotIn("private", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
