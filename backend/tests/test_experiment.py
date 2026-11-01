"""Auditoría independiente y ausencia de fuga temporal en el motor real."""

from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.experiment import linear_audit, mean_audit
from app.analytics.forecast import predict
from app.db.models import Pedido
from tests import test_analytics


class IndependentAuditTests(unittest.TestCase):
    def test_closed_form_linear_growth_has_exact_zero_mae(self):
        result = linear_audit([4 * (day + 1) for day in range(10)])
        self.assertEqual(result["training_days"], 8)
        self.assertEqual(result["validation_days"], 2)
        self.assertEqual(result["mae"], 0)
        self.assertEqual(result["future_daily"], [Decimal(value) for value in (44, 48, 52, 56, 60, 64, 68)])

    def test_validation_changes_do_not_change_training_predictions(self):
        first = linear_audit([4, 8, 12, 16, 20, 24, 28, 32, 36, 40])
        spiked = linear_audit([4, 8, 12, 16, 20, 24, 28, 32, 360, 400])
        self.assertEqual(first["validation_predictions"], spiked["validation_predictions"])
        self.assertGreater(spiked["mae"], first["mae"])


class ForecastTemporalAuditTests(unittest.TestCase):
    setUp = test_analytics.ForecastTests.setUp
    configure_client = test_analytics.ForecastTests.configure_client
    sign_in = test_analytics.ForecastTests.sign_in
    generate = test_analytics.ForecastTests.generate

    def test_real_fit_uses_training_only_and_includes_zero_sales_days(self):
        with Session(self.engine) as db:
            test_analytics.historical_orders(db)
            start = test_analytics.TODAY - timedelta(days=35)
            for order in db.scalars(select(Pedido).where(Pedido.id_restaurante == 1, Pedido.estado == "Entregado")):
                if (order.fecha_hora.date() - start).days in (3, 7):
                    order.estado = "No entregado"
            db.commit()
        events = []
        def observed(values, start, offset, method):
            events.append((len(values), offset))
            return predict(values, start, offset, method)
        with patch("app.analytics.forecast.predict", side_effect=observed):
            response = self.generate()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(all(end <= offset for end, offset in events))
        self.assertEqual({end for end, offset in events}, {21, 28, 35})
        values = [(day % 7 + 1) * 4 if day not in (3, 7) else 0 for day in range(35)]
        audit = mean_audit(values)
        self.assertLessEqual(abs(Decimal(response.json()["predicciones"][0]["valor_metrica"]) - audit["mae"]), Decimal(".000001"))
