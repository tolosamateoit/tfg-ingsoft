"""Generación offline: corte inclusivo, cobertura, asociaciones y recetas."""

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
import unittest

from app.demo_history.preparation import CATALOG, INVENTORY, plan_for
from app.demo_history.plan import LOCAL


class PreparationPlanTests(unittest.TestCase):
    def test_reproducible_coverage_patterns_and_valid_stock(self):
        plan = plan_for()
        self.assertEqual(plan, plan_for())
        self.assertNotEqual(plan["fingerprint"], plan_for(seed=42)["fingerprint"])
        days = Counter(row["fecha_hora"].astimezone(LOCAL).date() for row in plan["orders"])
        self.assertEqual((len(days), min(days), max(days)), (90, date(2026, 8, 3), date(2026, 10, 31)))
        weekend = [n for day, n in days.items() if day.weekday() >= 5]
        weekday = [n for day, n in days.items() if day.weekday() < 5]
        self.assertGreater(sum(weekend) / len(weekend), sum(weekday) / len(weekday))
        sold = Counter()
        pairs = Counter()
        intervals = defaultdict(list)
        for row in plan["orders"]:
            sold.update(dict(row["items"]))
            items = dict(row["items"])
            for pair in ((1, 6), (3, 7)):
                pairs[pair] += all(p in items for p in pair)
            self.assertEqual(row["importe_total"], sum(plan["products"][p]["precio"] * q for p, q in row["items"]))
            if "courier" in row:
                intervals[row["courier"]].append((row["assigned"], row["end"]))
        self.assertEqual(set(sold), set(range(len(CATALOG))))
        self.assertTrue(all(n > 100 for n in pairs.values()))
        for rows in intervals.values():
            rows.sort()
            self.assertTrue(all(a[1] <= b[0] for a, b in zip(rows, rows[1:])))
        running = defaultdict(Decimal)
        for m in sorted(plan["movements"], key=lambda m: m["fecha_hora"]):
            running[m["ingredient"]] += m["cantidad"]
            self.assertGreaterEqual(running[m["ingredient"]], 0)
        self.assertEqual(dict(running), plan["stock"])

    def test_packaged_units_costs_and_cutoff(self):
        for i in (6, 7, 8):
            recipe = CATALOG[i][3]
            self.assertEqual(len(recipe), 1)
            self.assertEqual(recipe[0][1], "1")
            self.assertEqual(INVENTORY[recipe[0][0]][1], "unidad")
        for product in plan_for()["products"]:
            self.assertGreater(product["precio"], product["costo_unitario"])
            self.assertGreater(product["costo_unitario"], 0)
        with self.assertRaises(ValueError):
            plan_for(date(2026, 11, 1))
