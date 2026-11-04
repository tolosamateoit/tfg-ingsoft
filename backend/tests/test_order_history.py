"""Mismas operaciones persistidas en pedidos, detalle, preparación y entregas."""

from datetime import UTC, datetime
import os
import unittest
from unittest.mock import patch

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.api.logistics import router as logistics_router
from app.api.preparation import router as preparation_router
from app.db.models import DetallePedido, Entrega, HistorialPedido, Pedido, RecetaDetalle, Restaurante
from tests import test_orders, test_orders_postgresql
from tests.auth_support import HEADERS


class OrderHistoryTests(unittest.TestCase):
    setUp = test_orders.OrderReadTests.setUp
    sign_in = test_orders.OrderReadTests.sign_in

    def configure_client(self):
        if self.engine.dialect.name == "sqlite":
            lock = patch("app.preparation.service.lock_order_relations")
            lock.start(); self.addCleanup(lock.stop)
        test_orders.OrderReadTests.configure_client(self)
        self.app.include_router(logistics_router, prefix="/api")
        self.app.include_router(preparation_router, prefix="/api")
        self.sign_in(1)

    def add_order(self, db, when, state="Entregado"):
        row = Pedido(id_restaurante=1, id_cliente=1, fecha_hora=when, estado=state,
                     direccion_entrega="Prueba", medio_pago="efectivo", estado_pago="pendiente",
                     importe_total=200, costo_total=20, distancia_km=1)
        db.add(row); db.flush()
        db.add(DetallePedido(id_pedido=row.id_pedido, id_producto=1, cantidad=2, precio_unitario=100))
        return row.id_pedido

    def test_day_uses_maximum_local_date_history_keeps_old_orders_and_ties(self):
        with Session(self.engine) as db:
            earlier = self.add_order(db, datetime(2026, 10, 31, 2, 59, 59, tzinfo=UTC))
            start = self.add_order(db, datetime(2026, 10, 31, 3, tzinfo=UTC))
            end = self.add_order(db, datetime(2026, 11, 1, 2, 59, 59, tzinfo=UTC))
            tied = self.add_order(db, datetime(2026, 11, 1, 2, 59, 59, tzinfo=UTC))
            db.commit()
        day = self.client.get("/api/pedidos?periodo=dia").json()
        self.assertEqual(day["fecha_operativa"], "2026-10-31")
        self.assertEqual([r["id_pedido"] for r in day["pedidos"]], [tied, end, start])
        history = self.client.get("/api/pedidos?periodo=historial&limit=2").json()
        ids = []
        for offset in range(0, history["total"], 2):
            page = self.client.get(f"/api/pedidos?periodo=historial&limit=2&offset={offset}").json()
            ids.extend(r["id_pedido"] for r in page["pedidos"])
        self.assertEqual(ids, [tied, end, start, earlier, 1])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.client.get("/api/pedidos/1").status_code, 200)
        self.assertEqual(self.client.get("/api/pedidos/2").status_code, 404)
        with Session(self.engine) as db:
            future = self.add_order(db, datetime(2026, 11, 2, 3, tzinfo=UTC), "Nuevo")
            db.commit()
        latest = self.client.get("/api/pedidos?periodo=dia").json()
        self.assertEqual(latest["fecha_operativa"], "2026-11-02")
        self.assertEqual([r["id_pedido"] for r in latest["pedidos"]], [future])
        self.assertEqual(self.client.get("/api/pedidos?periodo=historial").json()["total"], 6)

    def test_real_creation_keeps_history_and_summaries_match_delivery_and_detail(self):
        with Session(self.engine) as db:
            db.add(RecetaDetalle(id_producto=1, id_insumo=1, cantidad=1, unidad='kg'))
            db.commit()
        before = self.client.get("/api/pedidos?periodo=historial").json()
        saved = self.client.post(test_orders.CREATE, headers=HEADERS, json=test_orders.ORDER)
        self.assertEqual(saved.status_code, 201, saved.text)
        oid = saved.json()["id_pedido"]
        after = self.client.get("/api/pedidos?periodo=historial").json()
        self.assertEqual(after["total"], before["total"] + 1)
        self.assertTrue({r["id_pedido"] for r in before["pedidos"]} <= {r["id_pedido"] for r in after["pedidos"]})
        row = next(r for r in after["pedidos"] if r["id_pedido"] == oid)
        details = saved.json()["detalles"]
        expected = ", ".join(f"{d['cantidad']} × {d['nombre']}" for d in details)
        self.assertEqual(row["resumen_productos"], expected)
        self.assertIsNone(row["id_entrega"])
        self.assertIsNone(self.client.get(f"/api/pedidos/{oid}/seguimiento").json()["entrega"])
        # Una entrega real ya existente debe ser idéntica en todos los accesos.
        row = next(r for r in after["pedidos"] if r["id_pedido"] == 1)
        delivery = next(r for r in self.client.get("/api/entregas").json() if r["id_pedido"] == 1)
        detail = self.client.get("/api/pedidos/1").json()
        tracking = self.client.get("/api/pedidos/1/seguimiento").json()
        for data in (row, detail):
            self.assertEqual(data["id_entrega"], delivery["id_entrega"])
            self.assertEqual(data["repartidor"], delivery["repartidor"])
            self.assertEqual(data["resumen_productos"], delivery["resumen_productos"])
        self.assertEqual(tracking["entrega"]["id_entrega"], row["id_entrega"])

    def test_bulk_queries_are_bounded_for_twenty_rows_and_access_is_scoped(self):
        with Session(self.engine) as db:
            for _ in range(25):
                self.add_order(db, datetime(2026, 10, 31, 15, tzinfo=UTC))
            db.commit()
        statements = []
        def capture(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            response = self.client.get("/api/pedidos?periodo=historial&limit=20")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["pedidos"]), 20)
        self.assertLessEqual(len(statements), 9)  # incluye validación de sesión; no N+1
        self.assertTrue(all(r["resumen_productos"] for r in response.json()["pedidos"]))
        for query in ("periodo=otro", "limit=101", "offset=-1"):
            self.assertEqual(self.client.get(f"/api/pedidos?{query}").status_code, 422)
        self.sign_in(2)
        rows = self.client.get("/api/pedidos?periodo=historial").json()["pedidos"]
        self.assertEqual({r["id_restaurante"] for r in rows}, {2})
        self.assertEqual(self.client.get("/api/pedidos/1/seguimiento").status_code, 404)
        self.sign_in(5)
        own = self.client.get("/api/pedidos?periodo=historial")
        self.assertEqual(own.status_code, 200)
        self.assertTrue(all(row['id_repartidor'] == 1 for row in own.json()['pedidos']))
        self.assertTrue(all(r["id_repartidor"] == 1 for r in self.client.get("/api/entregas").json()))
        self.sign_in(3)
        self.assertEqual(self.client.get("/api/pedidos?periodo=dia").status_code, 403)

    def test_preparation_trace_matches_order_and_tracking_without_duplicate_event(self):
        # Receta local real, estados permitidos y timestamps del servidor.
        with Session(self.engine) as db:
            db.add(RecetaDetalle(id_producto=1, id_insumo=1, cantidad="0.2", unidad="kg"))
            db.commit()
        path = "/api/restaurantes/1/pedidos/1/preparacion"
        before = self.client.get(path).json()
        payload = {"estado": "En preparación", "version": before["version"]}
        saved = self.client.put(path, headers=HEADERS, json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        repeat = self.client.put(path, headers=HEADERS, json=payload)
        self.assertEqual(repeat.status_code, 200, repeat.text)
        current = self.client.get("/api/pedidos/1").json()
        tracking = self.client.get("/api/pedidos/1/seguimiento").json()
        self.assertEqual(current["estado"], tracking["estado_pedido"])
        self.assertEqual(current["estado"], "En preparación")
        self.assertEqual(len(tracking["historial"]), 1)
        self.assertEqual(tracking["historial"][0]["fecha_hora"], saved.json()["historial"][0]["fecha_hora"])


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Requiere PostgreSQL local descartable")
class OrderHistoryPostgreSQLTests(OrderHistoryTests):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables
