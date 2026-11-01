"""Integración exclusivamente local: adición, preservación, rechazo e idempotencia."""

from datetime import date
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Pedido, Restaurante
from app.demo_history.preparation import load, plan_for, snapshot, validate
from app.demo_history.storage import TABLES
from app.orders.operational_date import operational_date
from tests import test_orders_postgresql


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class PreparationPostgreSQLTests(unittest.TestCase):
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables

    def configure_client(self):
        pass

    def setUp(self):
        test_orders_postgresql.OrderReadPostgreSQLTests.setUp(self)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.plan = plan_for()
        with self.engine.begin() as c:
            # Solo fixture descartable: alinear identidades insertadas explícitamente.
            for name, table in TABLES.items():
                if len(table.primary_key.columns) == 1:
                    col = next(iter(table.primary_key.columns))
                    if col.identity is not None:
                        c.execute(text(f"SELECT setval(pg_get_serial_sequence('{name}','{col.name}'), coalesce((SELECT max({col.name}) FROM {name}),1), EXISTS(SELECT 1 FROM {name}))"))
            c.execute(text("UPDATE restaurante SET nombre='Rotisería del Pueblo' WHERE id_restaurante=1"))
            c.execute(text("UPDATE producto SET nombre='Milanesa' WHERE id_producto=1"))

    def test_load_reuses_product_preserves_orders_and_idempotence(self):
        with Session(self.engine) as db:
            before = snapshot(db)
        result = load(self.engine, 1, self.plan, self.output)
        self.assertEqual(result["products"], 10)
        self.assertEqual(result["ingredients"], 21)  # dos insumos previos con otros nombres
        self.assertEqual(result["couriers"], 6)  # dos previos y cuatro nuevos
        self.assertTrue(result["existing_records_preserved"])
        self.assertEqual(result["operational_date"], "2026-10-31")
        with Session(self.engine) as db:
            loaded = snapshot(db)
            for table in ("pedido", "detalle_pedido", "entrega", "usuario", "movimiento_stock", "historial_pedido"):
                keys = [col.name for col in TABLES[table].primary_key.columns]
                after = {tuple(r[k] for k in keys): r for r in loaded[table]}
                for row in before[table]:
                    self.assertEqual(row, after[tuple(row[k] for k in keys)])
        second = load(self.engine, 1, self.plan, self.output)
        self.assertEqual(second["action"], "unchanged")
        with Session(self.engine) as db:
            self.assertEqual(snapshot(db), loaded)
        with self.assertRaises(ValueError):
            load(self.engine, 1, plan_for(seed=42), self.output)
        with Session(self.engine) as db:
            self.assertEqual(snapshot(db), loaded)
            # Las restricciones deben rechazar FK válidas de restaurantes distintos.
            for statement in (
                "INSERT INTO receta_detalle VALUES (1,3,1,'kg')",
                "INSERT INTO detalle_pedido(id_pedido,id_producto,cantidad,precio_unitario) VALUES (1,2,1,100)",
                "UPDATE entrega SET id_repartidor=2 WHERE id_pedido=1",
                "INSERT INTO movimiento_stock(id_insumo,id_pedido,tipo,cantidad) VALUES(3,1,'consumo',-1)",
                "INSERT INTO historial_pedido(id_pedido,id_usuario,tipo_evento,estado) VALUES(1,2,'estado','Nuevo')",
            ):
                with self.assertRaises(IntegrityError):
                    with db.begin_nested():
                        db.execute(text(statement))
            validate(db, 1, self.plan)

    def test_failure_rolls_back_and_wrong_target_is_rejected(self):
        with Session(self.engine) as db:
            before = snapshot(db)
        with patch("app.demo_history.preparation.validate", side_effect=ValueError("Falla de validación")):
            with self.assertRaises(ValueError):
                load(self.engine, 1, self.plan, self.output)
        with Session(self.engine) as db:
            self.assertEqual(snapshot(db), before)
        with self.assertRaises(ValueError):
            load(self.engine, 2, self.plan, self.output)

    def test_operational_date_local_boundary_empty_and_isolation(self):
        with Session(self.engine) as db, db.begin():
            self.assertEqual(operational_date(db, 1), date(2026, 10, 25))
            order = db.get(Pedido, 1)
            db.execute(text("UPDATE pedido SET fecha_hora='2026-11-01 01:30:00+00' WHERE id_pedido=1"))
            self.assertEqual(operational_date(db, 1), date(2026, 10, 31))
            self.assertEqual(operational_date(db, 2), date(2026, 10, 25))
            empty = Restaurante(nombre="Vacío", direccion="Prueba", horario_atencion="Prueba", abierto=False,
                                costo_fijo_entrega=0, costo_por_km=0)
            db.add(empty); db.flush()
            self.assertIsNone(operational_date(db, empty.id_restaurante))
            with self.assertRaises(ValueError):
                operational_date(db, 99999)
            with self.assertRaises(ValueError):
                operational_date(db, True)
