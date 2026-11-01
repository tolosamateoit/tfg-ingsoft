"""Estructura del DER y compilación PostgreSQL, sin abrir conexiones."""

import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from app.core.config import DatabaseSettings
from app.db import models  # noqa: F401 - registrar todos los modelos
from app.db.base import Base
from app.db.engine import build_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]

DER_COLUMNS = {
    "restaurante": "id_restaurante nombre direccion horario_atencion abierto costo_fijo_entrega costo_por_km",
    "usuario": "id_usuario id_restaurante correo nombre hash_contrasena telefono rol activo",
    "cliente": "id_cliente id_usuario nombre telefono direccion referencia_local zona_entrega",
    "producto": "id_producto id_restaurante nombre precio costo_unitario activo",
    "insumo": "id_insumo id_restaurante nombre unidad stock_actual costo_unitario",
    "receta_detalle": "id_producto id_insumo cantidad unidad",
    "pedido": "id_pedido id_restaurante id_cliente fecha_hora estado direccion_entrega referencia_local medio_pago estado_pago importe_total puntaje_prioridad factores_prioridad zona_entrega distancia_km costo_total",
    "detalle_pedido": "id_detalle id_pedido id_producto cantidad precio_unitario",
    "repartidor": "id_repartidor id_usuario zona estado_disponibilidad",
    "historial_repartidor": "id_historial_disp id_repartidor estado fecha_hora",
    "entrega": "id_entrega id_pedido id_repartidor fecha_asignacion estado costo_repartidor",
    "historial_pedido": "id_historial id_pedido id_usuario fecha_hora tipo_evento estado detalle",
    "movimiento_stock": "id_movimiento id_insumo id_pedido fecha_hora tipo cantidad motivo",
    "prediccion_demanda": "id_prediccion id_producto periodo_inicio periodo_fin demanda_estimada modelo nombre_metrica valor_metrica generada_en",
    "alerta": "id_alerta id_restaurante tipo descripcion valor_observado valor_referencia fecha_hora estado",
}


class ModelStructureTests(unittest.TestCase):
    def test_entities_and_columns_match_der(self):
        self.assertEqual(set(Base.metadata.tables), set(DER_COLUMNS))
        for name, columns in DER_COLUMNS.items():
            with self.subTest(table=name):
                approved = {"descripcion", "imagen_url"} if name == "producto" else set()
                self.assertEqual(set(Base.metadata.tables[name].columns.keys()), set(columns.split()) | approved)

    def test_approved_product_presentation_attributes_are_optional(self):
        for name in ("descripcion", "imagen_url"):
            self.assertTrue(Base.metadata.tables["producto"].c[name].nullable)

    def test_mappers_and_postgresql_ddl_compile(self):
        configure_mappers()
        for table in Base.metadata.sorted_tables:
            with self.subTest(table=table.name):
                ddl = str(CreateTable(table).compile(dialect=dialect()))
                self.assertIn("CREATE TABLE", ddl)
                self.assertTrue(table.primary_key.columns)

    def test_recipe_composite_primary_key(self):
        self.assertEqual(
            list(Base.metadata.tables["receta_detalle"].primary_key.columns.keys()),
            ["id_producto", "id_insumo"],
        )

    def test_unique_attributes_of_der(self):
        for name, column in (
            ("usuario", "correo"), ("cliente", "id_usuario"),
            ("repartidor", "id_usuario"), ("entrega", "id_pedido"),
        ):
            with self.subTest(table=name, column=column):
                table = Base.metadata.tables[name]
                self.assertTrue(any(
                    isinstance(constraint, UniqueConstraint)
                    and list(constraint.columns.keys()) == [column]
                    for constraint in table.constraints
                ))

    def test_foreign_keys_resolve_and_do_not_cascade_deletion(self):
        for table in Base.metadata.tables.values():
            for foreign_key in table.foreign_keys:
                with self.subTest(table=table.name, column=foreign_key.parent.name):
                    self.assertIn(foreign_key.column.table.name, DER_COLUMNS)
                    self.assertEqual(foreign_key.ondelete, "RESTRICT")
                    self.assertEqual(foreign_key.onupdate, "RESTRICT")

    def test_optional_relationships(self):
        self.assertTrue(Base.metadata.tables["usuario"].c.id_restaurante.nullable)
        self.assertTrue(Base.metadata.tables["movimiento_stock"].c.id_pedido.nullable)
        self.assertFalse(Base.metadata.tables["entrega"].c.id_repartidor.nullable)

    def test_stock_may_be_negative_and_repreparation_not_blocked(self):
        insumo = Base.metadata.tables["insumo"]
        self.assertFalse(any(
            isinstance(constraint, CheckConstraint) and "stock_actual" in str(constraint.sqltext)
            for constraint in insumo.constraints
        ))
        movement = Base.metadata.tables["movimiento_stock"]
        self.assertFalse(any(isinstance(constraint, UniqueConstraint) for constraint in movement.constraints))


class MigrationSafetyTests(unittest.TestCase):
    def test_engine_construction_does_not_connect_and_masks_password(self):
        settings = DatabaseSettings(
            host="example.invalid", port=5432, dbname="postgres", user="test-user",
            password="test password@#%", sslrootcert="test-ca.crt", connect_timeout=5,
        )
        with patch("psycopg.connect") as connect:
            engine = build_engine(settings)
            self.addCleanup(engine.dispose)
            connect.assert_not_called()
            self.assertEqual(engine.url.password, settings.password)
            self.assertNotIn(settings.password, str(engine.url))
            self.assertTrue(engine.hide_parameters)

    def test_online_alembic_is_blocked_before_engine_creation(self):
        configuration = Config(str(BACKEND_DIR / "alembic.ini"))
        with patch("app.db.engine.build_engine") as engine:
            with self.assertRaisesRegex(CommandError, "Acceso online bloqueado"):
                command.current(configuration)
            engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
