"""Carga, respaldo, reinicio y motores reales sobre PostgreSQL local descartable."""

from datetime import date, timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.analytics.forecast import generate_forecast
from app.analytics.metrics import metrics
from app.analytics.schemas import PeriodInput
from app.db.models import Alerta, DetallePedido, HistorialPedido, MovimientoStock, Pedido, PrediccionDemanda, Restaurante, Usuario
from app.demo_history.plan import MARKER, OWNER_EMAIL, build_plan
from app.demo_history.storage import TABLES, bindings, decode, find_restaurant, load_dataset, outside_fingerprint, scope
from app.demo_history.validation import validate_dataset
from app.logistics.priority import priorities
from app.preparation.service import consumption
from tests import test_orders_postgresql


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable; nunca Supabase")
class HistoricalPostgreSQLTests(unittest.TestCase):
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables

    @classmethod
    def setUpClass(cls):
        cls.plan = build_plan(date(2026, 10, 31))

    def configure_client(self):
        pass

    def setUp(self):
        test_orders_postgresql.OrderReadPostgreSQLTests.setUp(self)
        self.directory = TemporaryDirectory(prefix="oliva-history-test-")
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        with self.engine.begin() as connection:
            for name, table in TABLES.items():
                if len(table.primary_key.columns) != 1:
                    continue
                column = next(iter(table.primary_key.columns))
                if column.identity is not None:
                    connection.execute(text(f"SELECT setval(pg_get_serial_sequence('{name}', '{column.name}'), coalesce((SELECT max({column.name}) FROM {name}), 1), EXISTS(SELECT 1 FROM {name}))"))
            # Nombre igual a propósito: el restaurante anterior jamás se selecciona por nombre.
            connection.execute(text("UPDATE restaurante SET nombre='Rotisería del Pueblo' WHERE id_restaurante=1"))

    def load(self, **options):
        return load_dataset(self.engine, self.plan, output=self.output, **options)

    def test_load_validate_idempotence_backup_and_unchanged_other_restaurants(self):
        with Session(self.engine) as db:
            original = outside_fingerprint(db)
        result = self.load()
        self.assertEqual((result["orders"], result["products"], result["ingredients"], result["movements"]), (2407, 8, 15, 12416))
        self.assertEqual(result["days"], 90)
        self.assertEqual((result["predictions"], result["alerts"]), (0, 0))
        self.assertTrue(result["outside_unchanged"])
        self.assertTrue(Path(result["credentials"]).is_file())
        second = self.load()
        self.assertEqual(second["action"], "unchanged")
        backup = json.loads(Path(second["backup"]).read_text(encoding="utf-8"), object_hook=decode)
        self.assertEqual(len(backup["tables"]["pedido"]), 2407)
        with Session(self.engine) as db:
            self.assertEqual(outside_fingerprint(db, scope(db, result["restaurant_id"])), original)
            self.assertEqual(db.scalar(select(func.count()).select_from(Restaurante).where(Restaurante.nombre == 'Rotisería del Pueblo')), 2)

    def test_reset_requires_correct_id_preserves_catalog_and_credentials(self):
        result = self.load(); rid = result["restaurant_id"]
        with Session(self.engine) as db:
            before = scope(db, rid)
        for wrong in (None, 1):
            with self.assertRaises(ValueError):
                self.load(reset=True, restaurant_id=wrong)
        refreshed = self.load(reset=True, restaurant_id=rid)
        self.assertEqual(refreshed["action"], "reset")
        self.assertIsNone(refreshed["credentials"])
        self.assertEqual(refreshed["fingerprint"], result["fingerprint"])
        with Session(self.engine) as db:
            after = scope(db, rid)
            for table in ("usuario", "cliente", "producto", "receta_detalle", "repartidor"):
                self.assertEqual(before[table], after[table])
            self.assertNotEqual(before["pedido"][0]["id_pedido"], after["pedido"][0]["id_pedido"])
            all_before = outside_fingerprint(db)
        with patch("app.demo_history.validation.validate_dataset", side_effect=ValueError("Reinicio fallido")):
            with self.assertRaises(ValueError):
                self.load(reset=True, restaurant_id=rid)
        with Session(self.engine) as db:
            self.assertEqual(outside_fingerprint(db), all_before)

    def test_rejects_unmarked_records_and_backup_failure_before_reset(self):
        result = self.load(); rid = result["restaurant_id"]
        with Session(self.engine) as db:
            order = db.scalar(select(Pedido).where(Pedido.id_restaurante == rid).order_by(Pedido.id_pedido))
            order.referencia_local = "Pedido registrado manualmente"
            db.commit()
            before = outside_fingerprint(db)
        with self.assertRaisesRegex(ValueError, "sin marca"):
            self.load(reset=True, restaurant_id=rid)
        with Session(self.engine) as db:
            self.assertEqual(outside_fingerprint(db), before)
        with patch("app.demo_history.storage.backup_scope", side_effect=OSError("Respaldo no disponible")):
            with self.assertRaises(OSError):
                self.load(reset=True, restaurant_id=rid)
        with Session(self.engine) as db:
            self.assertEqual(outside_fingerprint(db), before)

    def test_failure_rolls_back_whole_new_dataset(self):
        with Session(self.engine) as db:
            before = outside_fingerprint(db)
        with patch("app.demo_history.validation.validate_dataset", side_effect=ValueError("Falla controlada")):
            with self.assertRaises(ValueError):
                self.load()
        with Session(self.engine) as db:
            self.assertEqual(outside_fingerprint(db), before)
            self.assertIsNone(find_restaurant(db))

    def test_customer_cross_restaurant_reference_prevents_reset(self):
        result = self.load(); rid = result["restaurant_id"]
        with Session(self.engine) as db:
            ids = bindings(db, rid, self.plan)
            order = Pedido(id_restaurante=2, id_cliente=ids["clients"][0], estado="Nuevo", direccion_entrega="Mitre 450",
                           medio_pago="efectivo", estado_pago="pendiente", importe_total=100, costo_total=10, distancia_km=1)
            db.add(order); db.flush()
            db.add(DetallePedido(id_pedido=order.id_pedido, id_producto=2, cantidad=1, precio_unitario=100))
            db.commit()
            before = outside_fingerprint(db)
        with self.assertRaisesRegex(ValueError, "pedidos externos"):
            self.load(reset=True, restaurant_id=rid)
        with Session(self.engine) as db:
            self.assertEqual(outside_fingerprint(db), before)

    def test_real_motors_and_hu04_use_the_history_without_persisting_results(self):
        result = self.load(); rid = result["restaurant_id"]
        with self.engine.connect() as connection:
            outer = connection.begin()
            with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                with patch("app.analytics.forecast.utc_today", return_value=date(2026, 10, 31)), patch("app.analytics.metrics.utc_today", return_value=date(2026, 10, 31)):
                    forecast = generate_forecast(db, rid)
                    self.assertEqual(forecast.estado, "Predicción generada")
                    self.assertEqual(len(forecast.predicciones), 6)
                    self.assertEqual(len(forecast.productos_sin_ventas), 2)
                    self.assertTrue(all(item.nombre_metrica == "MAE" and item.valor_metrica.is_finite() for item in forecast.predicciones))
                    self.assertTrue(any(item.faltante > 0 for item in forecast.insumos))
                    self.assertTrue(any(item.faltante == 0 for item in forecast.insumos))
                    owner = db.scalar(select(Usuario).where(Usuario.correo == OWNER_EMAIL))
                    observed = metrics(db, owner, rid, PeriodInput(inicio=date(2026, 10, 17), fin=date(2026, 10, 30)))
                    # La consulta visible limita las últimas 100 alertas; validar el cálculo completo.
                    alert_types = set(db.scalars(select(Alerta.tipo).where(Alerta.id_restaurante == rid).distinct()))
                    self.assertTrue({"preparacion", "entrega", "importe", "stock"} <= alert_types, alert_types)
                    self.assertTrue(all(count > 0 for count in observed.muestras.values()))
                    queue = priorities(db, rid)
                    self.assertEqual(len(queue.pedidos), 3)
                    self.assertEqual([row.puntaje_prioridad for row in queue.pedidos], sorted((row.puntaje_prioridad for row in queue.pedidos), reverse=True))
                    recipe_orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == rid).order_by(Pedido.id_pedido).limit(3)).all()
                    for order in recipe_orders:
                        _, amounts = consumption(db, rid, order.id_pedido)
                        used = db.execute(select(MovimientoStock.id_insumo, func.sum(MovimientoStock.cantidad)).where(MovimientoStock.id_pedido == order.id_pedido).group_by(MovimientoStock.id_insumo)).all()
                        self.assertEqual({id: -qty for id, qty in used}, amounts)
            outer.rollback()
        with Session(self.engine) as db:
            report = validate_dataset(db, rid, self.plan)
            self.assertEqual((report["predictions"], report["alerts"]), (0, 0))

    def test_derived_results_require_separate_explicit_clear_and_are_backed_up(self):
        result = self.load(); rid = result["restaurant_id"]
        with Session(self.engine) as db, patch("app.analytics.forecast.utc_today", return_value=date(2026, 10, 31)):
            generate_forecast(db, rid)
        with self.assertRaisesRegex(ValueError, "resultados de la aplicación"):
            self.load(reset=True, restaurant_id=rid)
        result = self.load(reset=True, restaurant_id=rid, clear_derived=True)
        backup = json.loads(Path(result["backup"]).read_text(encoding="utf-8"), object_hook=decode)
        self.assertEqual(len(backup["tables"]["prediccion_demanda"]), 6)
        self.assertEqual(result["predictions"], 0)
