import unittest
from unittest.mock import patch

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.dashboard import router as dashboard_router
from app.db.models import Alerta, Entrega, Insumo, Pedido, PrediccionDemanda, RecetaDetalle, Repartidor
from tests import test_analytics
from tests.auth_support import HEADERS

BASE = "/api/restaurantes/1"


class DashboardTests(unittest.TestCase):
    def test_ready_and_delivery_orders_are_counted_but_not_ranked(self):
        from tests.test_logistics import add_order
        with Session(self.engine) as db:
            for state in ('En preparación', 'Listo', 'Asignado', 'En camino'):
                add_order(db, estado=state)
            db.commit()
        response = self.dashboard()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['pedidos_por_estado'], {
            'Nuevo': 1, 'En preparación': 1, 'Listo': 1, 'Asignado': 1, 'En camino': 1})
        self.assertEqual({r['estado'] for r in response.json()['prioridades']['pedidos']}, {'Nuevo', 'En preparación'})

    def setUp(self):
        test_analytics.ForecastTests.setUp(self)
        lock = patch("app.logistics.priority.lock_order_relations")
        lock.start(); self.addCleanup(lock.stop)

    sign_in = test_analytics.ForecastTests.sign_in

    def configure_client(self):
        test_analytics.ForecastTests.configure_client(self)
        self.app.include_router(dashboard_router, prefix="/api")

    def dashboard(self, path=BASE, period=None):
        return self.client.post(path + "/dashboard", headers=HEADERS,
                                json=test_analytics.PERIOD if period is None else period)

    def test_owner_integrates_existing_results_without_training_another_model(self):
        with Session(self.engine) as db:
            test_analytics.historical_orders(db)
            test_analytics.indicator_history(db)
        prediction = self.client.post(BASE + "/predicciones", headers=HEADERS)
        self.assertEqual(prediction.status_code, 200, prediction.text)
        response = self.dashboard()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["id_restaurante"], 1)
        self.assertEqual(data["pedidos_por_estado"], {"Nuevo": 1})
        self.assertEqual([row["id_pedido"] for row in data["prioridades"]["pedidos"]], [1])
        self.assertTrue(all(row["id_repartidor"] in (1, 3) for row in data["entregas_recientes"]))
        self.assertEqual(len(data["alertas_activas"]), 4)
        self.assertIsNotNone(data["indicadores"]["promedios"]["preparacion"])
        self.assertEqual(data["prediccion_guardada"]["predicciones"][0]["id_prediccion"],
                         prediction.json()["predicciones"][0]["id_prediccion"])
        self.assertEqual(self.dashboard().status_code, 200)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(PrediccionDemanda)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Alerta)), 4)

    def test_dashboard_is_restricted_to_the_restaurant_owner(self):
        with Session(self.engine) as db:
            db.add_all([Alerta(id_restaurante=1, tipo="importe", descripcion="Importe privado", valor_observado=100, valor_referencia=50, estado="Activa"),
                        Alerta(id_restaurante=1, tipo="stock", descripcion="Stock operativo", valor_observado=-1, valor_referencia=0, estado="Activa")])
            db.commit()
        self.sign_in(1)
        response = self.dashboard()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertNotIn("Importe privado", response.text)
        self.assertEqual(self.dashboard("/api/restaurantes/2").status_code, 403)
        self.sign_in(2)
        other = self.dashboard("/api/restaurantes/2")
        self.assertEqual(other.status_code, 403, other.text)

    def test_empty_restaurant_has_explicit_absence_instead_of_invented_results(self):
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = "Entregado"
            db.execute(delete(Entrega))
            db.execute(delete(RecetaDetalle))
            db.execute(delete(Insumo).where(Insumo.id_restaurante == 1))
            db.execute(delete(Repartidor).where(Repartidor.id_repartidor.in_((1, 3))))
            db.commit()
        response = self.dashboard(period={"inicio": "2019-01-01", "fin": "2019-01-02"})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["pedidos_por_estado"], {})
        self.assertEqual(data["entregas_recientes"], [])
        self.assertEqual(data["stock"], [])
        self.assertEqual(data["repartidores"]["repartidores"], [])
        self.assertTrue(all(value is None for value in data["indicadores"]["promedios"].values()))
        self.assertEqual(data["prediccion_guardada"]["estado"], "Sin predicciones guardadas")

    def test_roles_csrf_and_period_validation(self):
        self.assertEqual(self.client.post(BASE + "/dashboard", json=test_analytics.PERIOD).status_code, 403)
        self.assertEqual(self.dashboard(period={"inicio": "2026-10-27", "fin": "2026-10-26"}).status_code, 422)
        for user in (3, 5, 8):
            self.sign_in(user)
            self.assertEqual(self.dashboard().status_code, 403)
