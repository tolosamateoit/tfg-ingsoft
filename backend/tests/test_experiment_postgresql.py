"""Experimento sobre la carga real en PostgreSQL descartable; nunca Supabase."""

from datetime import date
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy.orm import Session

from app.analytics.experiment import audit_saved, run_experiment
from app.demo_history.plan import build_plan
from app.demo_history.storage import load_dataset, scope, digest
from tests import test_demo_history_postgresql


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class ExperimentPostgreSQLTests(unittest.TestCase):
    setUp = test_demo_history_postgresql.HistoricalPostgreSQLTests.setUp
    configure_client = test_demo_history_postgresql.HistoricalPostgreSQLTests.configure_client
    drop_test_tables = test_demo_history_postgresql.HistoricalPostgreSQLTests.drop_test_tables

    def test_services_audits_and_alert_idempotence_preserve_input_records(self):
        plan = build_plan(date(2026, 10, 31))
        loaded = load_dataset(self.engine, plan, output=self.output)
        self.assertEqual(loaded["restaurant_id"], 3)
        with Session(self.engine) as db:
            own = scope(db, 3)
            before = digest({key: rows for key, rows in own.items() if key not in {"prediccion_demanda", "alerta"}})
        path, report = run_experiment(self.engine, self.output, self.output)
        self.assertEqual(len(report["forecast_audit"]["products"]), 6)
        self.assertEqual(len(report["forecast_audit"]["omitted"]), 2)
        self.assertTrue(report["history_unchanged"] and report["outside_unchanged"])
        self.assertTrue(report["deduplication"]["identical_ids_and_values"])
        self.assertEqual(report["logistics"]["available_couriers"], 0)
        self.assertFalse(report["logistics"]["persisted"])
        self.assertEqual(audit_saved(path)["products_checked"], 6)
        with Session(self.engine) as db:
            own = scope(db, 3)
            self.assertEqual(before, digest({key: rows for key, rows in own.items() if key not in {"prediccion_demanda", "alerta"}}))
            self.assertEqual(len(own["prediccion_demanda"]), 6)
            self.assertGreater(len(own["alerta"]), 100)
