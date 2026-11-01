"""Paginación real, filtros combinados y permisos sin alterar alertas guardadas."""
from datetime import UTC, datetime
from decimal import Decimal
import os
import unittest

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Alerta
from tests import test_analytics, test_orders_postgresql

BASE = test_analytics.BASE + "/alertas"


class AlertPaginationTests(unittest.TestCase):
    setUp = test_analytics.ForecastTests.setUp
    configure_client = test_analytics.ForecastTests.configure_client
    sign_in = test_analytics.ForecastTests.sign_in

    def seed(self):
        with Session(self.engine) as db:
            for i in range(901):
                db.add(Alerta(id_restaurante=1, tipo=("importe", "entrega", "preparacion", "stock")[i % 4],
                              descripcion=f"qa:{i} | Observación {i}", valor_observado=Decimal("2.01") if i % 3 == 0 else Decimal("2"),
                              valor_referencia=1, estado="Resuelta" if i % 5 == 0 else "Activa",
                              fecha_hora=datetime(2026, 10, 30, 12, tzinfo=UTC)))
            db.add(Alerta(id_restaurante=2, tipo="stock", descripcion="Ajena", valor_observado=-1,
                          valor_referencia=0, estado="Activa"))
            db.commit()

    def snapshot(self):
        with Session(self.engine) as db:
            return list(db.execute(select(Alerta.id_alerta, Alerta.id_restaurante, Alerta.descripcion,
                Alerta.tipo, Alerta.estado, Alerta.valor_observado, Alerta.valor_referencia, Alerta.fecha_hora)
                .order_by(Alerta.id_alerta)).all())

    def test_all_901_stable_pages_no_duplicates_no_writes(self):
        self.seed(); before = self.snapshot(); ids = []
        for offset in range(0, 901, 25):
            response = self.client.get(BASE, params={"offset": offset})
            self.assertEqual(response.status_code, 200, response.text)
            page = response.json()
            self.assertEqual((page["total"], page["limit"], page["offset"]), (901, 25, offset))
            self.assertEqual(len(page["alertas"]), min(25, 901 - offset))
            ids += [row["id_alerta"] for row in page["alertas"]]
        self.assertEqual(len(set(ids)), 901)
        self.assertEqual(ids, sorted(ids, reverse=True))  # Desempate por ID, misma fecha.
        self.assertEqual(self.client.get(BASE, params={"offset": 925}).json()["alertas"], [])
        self.assertEqual(before, self.snapshot())

    def test_filters_compose_count_matches_rows_and_critical_boundary(self):
        self.seed()
        for severity, expected in (("critica", 301), ("advertencia", 600)):
            page = self.client.get(BASE, params={"severidad": severity, "limit": 100}).json()
            self.assertEqual(page["total"], expected)
            self.assertTrue(all(row["severidad"] == severity for row in page["alertas"]))
        page = self.client.get(BASE, params={"tipo": "importe", "estado": "Resuelta", "severidad": "critica"}).json()
        expected = len([i for i in range(901) if i % 4 == 0 and i % 5 == 0 and i % 3 == 0])
        self.assertEqual(page["total"], expected)
        self.assertTrue(all(row["tipo"] == "importe" and row["estado"] == "Resuelta" and row["severidad"] == "critica" for row in page["alertas"]))
        with Session(self.engine) as db:
            db.add(Alerta(id_restaurante=1, tipo="stock", descripcion="Faltante", valor_observado=-1, valor_referencia=0, estado="Activa"))
            db.commit()
        row = self.client.get(BASE, params={"tipo": "stock", "severidad": "critica"}).json()["alertas"][0]
        self.assertEqual(row["descripcion"], "Faltante")

    def test_invalid_parameters_permissions_and_empty_page(self):
        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"tipo": "otro"},
                       {"estado": "inventado"}, {"severidad": "alta"}):
            self.assertEqual(self.client.get(BASE, params=params).status_code, 422)
        self.assertEqual(self.client.get(BASE).json()["total"], 0)
        self.assertEqual(self.client.get("/api/restaurantes/2/alertas").status_code, 403)
        for user in (1, 3, 5):
            self.sign_in(user)
            self.assertEqual(self.client.get(BASE).status_code, 403)


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Solo PostgreSQL local descartable")
class AlertPaginationPostgreSQLTests(AlertPaginationTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables
