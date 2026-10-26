"""Integración opt-in EXCLUSIVAMENTE con una base LOCAL descartable y vacía.

TFG_TEST_POSTGRES_DSN debe apuntar a loopback y database tfg_test_*. Nunca usa
backend/.env. Si no se configura, estas pruebas se omiten explícitamente.
"""

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import psycopg
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

LOCAL_DSN = os.environ.get("TFG_TEST_POSTGRES_DSN")
BACKEND_DIR = Path(__file__).resolve().parents[1]


def local_test_engine(dsn):
    values = conninfo_to_dict(dsn)
    # No aceptar hostaddr, service ni overrides que eludan la comprobación local.
    if values.get("host") not in {"127.0.0.1", "localhost", "::1"} or not values.get("dbname", "").startswith("tfg_test_"):
        raise ValueError("Las pruebas requieren host loopback y base tfg_test_* descartable.")
    if set(values) - {"host", "port", "dbname", "user", "password", "sslmode"}:
        raise ValueError("Opciones de conexión no permitidas en pruebas locales.")
    return create_engine(
        URL.create("postgresql+psycopg"),
        creator=lambda: psycopg.connect(
            dsn, connect_timeout=5,
            hostaddr="::1" if values["host"] == "::1" else "127.0.0.1",
        ),
        poolclass=NullPool, hide_parameters=True,
    )


def seed(connection):
    statements = [
        "INSERT INTO restaurante VALUES (1,'R1','D1','H',true,0,0),(2,'R2','D2','H',true,0,0)",
        "INSERT INTO usuario (id_usuario,id_restaurante,correo,nombre,hash_contrasena,rol,activo) VALUES "
        "(1,1,'personal1@test.invalid','P1','test','personal',true),"
        "(2,2,'personal2@test.invalid','P2','test','personal',true),"
        "(3,NULL,'cliente1@test.invalid','C1','test','cliente',true),"
        "(4,NULL,'cliente2@test.invalid','C2','test','cliente',true),"
        "(5,1,'repartidor1@test.invalid','RP1','test','repartidor',true),"
        "(6,2,'repartidor2@test.invalid','RP2','test','repartidor',true)",
        "INSERT INTO cliente (id_cliente,id_usuario,nombre) VALUES (1,3,'C1'),(2,4,'C2')",
        "INSERT INTO repartidor (id_repartidor,id_usuario,estado_disponibilidad) VALUES (1,5,'Disponible'),(2,6,'Disponible')",
        "INSERT INTO producto VALUES (1,1,'P1',1000,500,true),(2,2,'P2',2000,1000,true)",
        "INSERT INTO insumo VALUES (1,1,'I1','g',10,1),(2,2,'I2','g',10,1)",
        "INSERT INTO pedido (id_pedido,id_restaurante,id_cliente,estado,direccion_entrega,medio_pago,estado_pago,importe_total,distancia_km,costo_total) "
        "VALUES (1,1,1,'Nuevo','D1','efectivo','pendiente',1000,1,500),(2,2,2,'Nuevo','D2','efectivo','pendiente',2000,1,1000)",
        "INSERT INTO detalle_pedido VALUES (1,1,1,1,1000),(2,2,2,1,2000)",
    ]
    for statement in statements:
        connection.exec_driver_sql(statement)


@unittest.skipUnless(LOCAL_DSN, "Sin PostgreSQL local descartable; no se utiliza Supabase")
class PostgreSQLConstraintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = local_test_engine(LOCAL_DSN)
        with cls.engine.connect() as connection:
            existing = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' LIMIT 1")).first()
            if existing:
                raise RuntimeError("La base local debe estar vacía; no se modificó su estructura.")
            connection.rollback()
            config = Config(str(BACKEND_DIR / "alembic.ini"))
            config.cmd_opts = SimpleNamespace(x=["approved=true"])
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()
            seed(connection)
            connection.commit()
        cls.config = config

    @classmethod
    def tearDownClass(cls):
        with cls.engine.connect() as connection:
            cls.config.attributes["connection"] = connection
            command.downgrade(cls.config, "base")
            connection.commit()
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.addCleanup(self.connection.close)
        self.addCleanup(lambda: self.transaction.rollback() if self.transaction.is_active else None)

    def rejects(self, sql):
        with self.assertRaises(IntegrityError):
            with self.connection.begin_nested():
                self.connection.exec_driver_sql(sql)

    def test_cross_restaurant_references_are_rejected(self):
        for sql in (
            "INSERT INTO receta_detalle VALUES (1,2,1,'g')",
            "INSERT INTO detalle_pedido VALUES (10,1,2,1,1000)",
            "INSERT INTO entrega (id_pedido,id_repartidor,estado,costo_repartidor) VALUES (1,2,'asignada',0)",
            "INSERT INTO movimiento_stock (id_insumo,id_pedido,tipo,cantidad) VALUES (2,1,'consumo',1)",
            "INSERT INTO historial_pedido (id_pedido,id_usuario,tipo_evento,estado) VALUES (1,2,'estado','Nuevo')",
            "INSERT INTO historial_pedido (id_pedido,id_usuario,tipo_evento,estado) VALUES (1,4,'estado','Nuevo')",
            "INSERT INTO repartidor (id_usuario,estado_disponibilidad) VALUES (4,'Disponible')",
        ):
            with self.subTest(sql=sql):
                self.rejects(sql)

    def test_same_restaurant_and_order_owner_history_are_allowed(self):
        self.connection.exec_driver_sql("INSERT INTO receta_detalle VALUES (1,1,1,'g')")
        self.connection.exec_driver_sql("INSERT INTO entrega (id_pedido,id_repartidor,estado,costo_repartidor) VALUES (1,1,'asignada',0)")
        for user in (1, 3, 5):
            self.connection.exec_driver_sql(f"INSERT INTO historial_pedido (id_pedido,id_usuario,tipo_evento,estado) VALUES (1,{user},'estado','Nuevo')")
        self.connection.exec_driver_sql("INSERT INTO movimiento_stock (id_insumo,tipo,cantidad) VALUES (1,'ajuste',-1)")

    def test_changes_in_referenced_records_cannot_break_integrity(self):
        for sql in (
            "INSERT INTO receta_detalle VALUES (1,1,1,'g')",
            "INSERT INTO entrega (id_pedido,id_repartidor,estado,costo_repartidor) VALUES (1,1,'asignada',0)",
            "INSERT INTO movimiento_stock (id_insumo,id_pedido,tipo,cantidad) VALUES (1,1,'consumo',1)",
            "INSERT INTO historial_pedido (id_pedido,id_usuario,tipo_evento,estado) VALUES (1,1,'estado','Nuevo'),(1,3,'estado','Nuevo')",
        ):
            self.connection.exec_driver_sql(sql)
        for sql in (
            "UPDATE producto SET id_restaurante=2 WHERE id_producto=1",
            "UPDATE insumo SET id_restaurante=2 WHERE id_insumo=1",
            "UPDATE pedido SET id_restaurante=2 WHERE id_pedido=1",
            "UPDATE usuario SET id_restaurante=2 WHERE id_usuario=1",
            "UPDATE usuario SET id_restaurante=2 WHERE id_usuario=5",
            "UPDATE cliente SET id_usuario=4 WHERE id_cliente=1",
            "UPDATE pedido SET id_cliente=2 WHERE id_pedido=1",
        ):
            with self.subTest(sql=sql):
                self.rejects(sql)

    def test_uniqueness_fk_and_value_checks(self):
        for sql in (
            "UPDATE usuario SET correo='personal1@test.invalid' WHERE id_usuario=2",
            "INSERT INTO receta_detalle VALUES (999,1,1,'g')",
            "INSERT INTO receta_detalle VALUES (1,1,0,'g')",
            "UPDATE detalle_pedido SET cantidad=0 WHERE id_detalle=1",
            "UPDATE producto SET precio=-1 WHERE id_producto=1",
            "DELETE FROM restaurante WHERE id_restaurante=1",
        ):
            with self.subTest(sql=sql):
                self.rejects(sql)
        self.connection.exec_driver_sql("UPDATE insumo SET stock_actual=-1 WHERE id_insumo=1")

    def test_deferred_cardinality_rejects_removing_last_detail(self):
        with self.assertRaises(IntegrityError):
            with self.connection.begin_nested():
                self.connection.exec_driver_sql("DELETE FROM detalle_pedido WHERE id_pedido=1")
                self.connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")

    def test_empty_order_and_primary_key_change_are_rejected_at_transaction_end(self):
        with self.assertRaises(IntegrityError):
            with self.connection.begin_nested():
                self.connection.exec_driver_sql("INSERT INTO pedido SELECT 10,id_restaurante,id_cliente,fecha_hora,estado,direccion_entrega,referencia_local,medio_pago,estado_pago,importe_total,puntaje_prioridad,factores_prioridad,zona_entrega,distancia_km,costo_total FROM pedido WHERE id_pedido=1")
                self.connection.exec_driver_sql("UPDATE pedido SET id_pedido=11 WHERE id_pedido=10")
                self.connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")

    def test_non_structural_updates_and_unlinked_reassignment_are_allowed(self):
        self.connection.exec_driver_sql("UPDATE producto SET precio=1100 WHERE id_producto=1")
        self.connection.exec_driver_sql("INSERT INTO producto VALUES (10,1,'Libre',1,1,true)")
        self.connection.exec_driver_sql("UPDATE producto SET id_restaurante=2 WHERE id_producto=10")

    def test_concurrent_reference_and_reassignment_cannot_both_commit(self):
        # Libera la transacción del test: ambas conexiones ven el fixture confirmado.
        self.transaction.rollback()
        with self.engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO producto VALUES (20,1,'Concurrente',1,1,true)")
        try:
            for first_reference in (True, False):
                with self.engine.connect() as first:
                    first.exec_driver_sql("INSERT INTO receta_detalle VALUES (20,1,1,'g')" if first_reference else "UPDATE producto SET id_restaurante=2 WHERE id_producto=20")
                    started = threading.Event()
                    finished = threading.Event()

                    def second_write():
                        try:
                            with self.engine.begin() as second:
                                second.exec_driver_sql("SET statement_timeout='5s'")
                                started.set()
                                second.exec_driver_sql("UPDATE producto SET id_restaurante=2 WHERE id_producto=20" if first_reference else "INSERT INTO receta_detalle VALUES (20,1,1,'g')")
                        finally:
                            finished.set()

                    with ThreadPoolExecutor(max_workers=1) as pool:
                        result = pool.submit(second_write)
                        self.assertTrue(started.wait(2))
                        self.assertFalse(finished.wait(0.2))
                        first.commit()
                        with self.assertRaises(IntegrityError):
                            result.result(timeout=6)
                with self.engine.begin() as cleanup:
                    cleanup.exec_driver_sql("DELETE FROM receta_detalle WHERE id_producto=20")
                    cleanup.exec_driver_sql("UPDATE producto SET id_restaurante=1 WHERE id_producto=20")
        finally:
            with self.engine.begin() as cleanup:
                cleanup.exec_driver_sql("DELETE FROM receta_detalle WHERE id_producto=20")
                cleanup.exec_driver_sql("DELETE FROM producto WHERE id_producto=20")


class LocalTestSafetyTests(unittest.TestCase):
    def test_remote_database_is_rejected_before_connecting(self):
        with self.assertRaises(ValueError):
            local_test_engine("host=remote.invalid dbname=tfg_test_demo user=test password=test")
        with self.assertRaises(ValueError):
            local_test_engine("host=127.0.0.1 dbname=postgres user=test password=test")


if __name__ == "__main__":
    unittest.main()
