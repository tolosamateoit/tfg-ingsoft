"""Plan reproducible sin base de datos, ni secretos, ni escrituras."""

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import patch

from app.demo_history.plan import INGREDIENTS, LOCAL, build_plan


class HistoricalPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = build_plan(date(2026, 10, 31))

    def test_fixed_seed_repeats_content_and_other_seed_changes_it_without_network(self):
        with patch("psycopg.connect", side_effect=AssertionError("No conectar")):
            self.assertEqual(self.plan, build_plan(date(2026, 10, 31)))
            self.assertNotEqual(self.plan["fingerprint"], build_plan(date(2026, 10, 31), seed=42)["fingerprint"])

    def test_ninety_days_weekends_trends_and_identifiable_cases(self):
        rows = self.plan["orders"]
        days = Counter(row["fecha_hora"].astimezone(LOCAL).date() for row in rows)
        self.assertEqual(len(days), 90)
        self.assertEqual((str(min(days)), str(max(days))), ("2026-08-02", "2026-10-30"))
        weekend = [count for day, count in days.items() if day.weekday() >= 5]
        weekdays = [count for day, count in days.items() if day.weekday() < 5]
        self.assertGreater(sum(weekend) / len(weekend), sum(weekdays) / len(weekdays) * 1.35)
        first, last = Counter(), Counter()
        for row in rows:
            if row["estado"] == "Entregado":
                target = first if row["day"] < 30 else last if row["day"] >= 60 else None
                if target is not None:
                    target.update(dict(row["items"]))
        self.assertGreater(last[2], first[2])
        self.assertGreater(last[4], first[4])
        self.assertLess(last[0], first[0])
        self.assertLess(last[5], first[5])
        self.assertTrue(any("preparacion_lenta" in row["tags"] for row in rows))
        self.assertTrue(any("entrega_lenta" in row["tags"] for row in rows))
        self.assertTrue(any(row["repeat"] for row in rows))
        self.assertTrue(any(row["importe_total"] > 100000 for row in rows))
        self.assertFalse(any(product >= 6 for row in rows if row["estado"] == "Entregado" for product, _ in row["items"]))

    def test_distances_ledger_and_delivery_availability(self):
        stocks = defaultdict(Decimal)
        for row in sorted(self.plan["movements"], key=lambda row: row["fecha_hora"]):
            stocks[row["ingredient"]] += row["cantidad"]
            if stocks[row["ingredient"]] < 0:
                self.assertEqual(row["tipo"], "ajuste")
                self.assertEqual(row["ingredient"], 10)
        self.assertEqual(dict(stocks), self.plan["stock"])
        self.assertEqual(len(stocks), len(INGREDIENTS))
        days = defaultdict(list)
        for row in self.plan["orders"]:
            self.assertGreaterEqual(row["distancia_km"], Decimal(".10"))
            self.assertLessEqual(row["distancia_km"], 5)
            self.assertEqual(row["distancia_km"], row["distancia_km"].quantize(Decimal(".01")))
            days[row["day"]].append(row)
        for rows in days.values():
            for row in rows:
                busy = {other["courier"] for other in rows if "courier" in other and other["assigned"] <= row["fecha_hora"] < other["end"]}
                self.assertLess(len(busy), 4)
