"""HU-06/HU-07 con sesiones reales; valores controlados solo en las fixtures."""

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.logistics import router as logistics_router
from app.api.preparation import router as preparation_router
from app.db.models import DetallePedido, Entrega, HistorialPedido, HistorialRepartidor, Insumo, Pedido, RecetaDetalle, Repartidor, Restaurante, Usuario
from app.logistics.priority import calculate
from app.logistics.service import ranked_couriers
from app.main import validation_error
from tests.auth_support import HEADERS, PASSWORD, override_database
from tests.menu_support import sqlite_menu_engine

BASE = "/api/restaurantes/1"


def add_order(db, *, estado="Listo", **kwargs):
    data = {"id_restaurante": 1, "id_cliente": 1, "fecha_hora": datetime(2026, 10, 26, tzinfo=UTC),
            "estado": estado, "direccion_entrega": "Dirección sintética", "medio_pago": "efectivo",
            "estado_pago": "pendiente", "importe_total": Decimal("100"), "costo_total": Decimal("10"),
            "distancia_km": Decimal("1")}
    order = Pedido(**{**data, **kwargs})
    db.add(order); db.flush()
    db.add(DetallePedido(id_pedido=order.id_pedido, id_producto=1, cantidad=1, precio_unitario=100))
    return order


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.engine = sqlite_menu_engine()
        self.addCleanup(self.engine.dispose)
        for target in ("app.auth.service.lock_email", "app.logistics.priority.lock_order_relations", "app.logistics.service.lock_order_relations", "app.preparation.service.lock_order_relations"):
            context = patch(target)
            context.start()
            self.addCleanup(context.stop)
        self.configure_client()

    def configure_client(self):
        with Session(self.engine) as db:
            db.execute(delete(Entrega))
            db.add(RecetaDetalle(id_producto=1, id_insumo=1, cantidad=Decimal("0.2"), unidad="kg"))
            db.commit()
        self.app = FastAPI()
        for router in (auth_router, logistics_router, preparation_router):
            self.app.include_router(router, prefix="/api")
        self.app.add_exception_handler(RequestValidationError, validation_error)
        override_database(self.app, self.engine)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.sign_in(1)

    def sign_in(self, user):
        self.client.cookies.clear()
        response = self.client.post("/api/auth/login", headers=HEADERS,
                                    json={"correo": f"u{user}@test.invalid", "contrasena": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)

    def test_formula_exact_decimals_floor_and_no_time_limit(self):
        now = datetime(2026, 10, 27, 12, tzinfo=UTC)
        order = Pedido(fecha_hora=now - timedelta(minutes=10001, seconds=59), distancia_km=Decimal("3.125"),
                       importe_total=Decimal("10000.12"), costo_total=Decimal("5500.01"))
        calculate(order, now)
        self.assertEqual(order.factores_prioridad, {"T": 10001, "D": "6.875", "G": "4.50011"})
        self.assertEqual(order.puntaje_prioridad, Decimal("10012.37511"))
        order.fecha_hora = now - timedelta(seconds=59, microseconds=999999)
        order.distancia_km = Decimal("20")
        order.costo_total = Decimal("20000")
        calculate(order, now)
        self.assertEqual(order.puntaje_prioridad, 0)

    def test_recalculation_persists_and_ties_use_oldest_then_id(self):
        with Session(self.engine) as db:
            # 30 segundos más antiguo, mismo minuto completo y misma prioridad.
            first = db.get(Pedido, 1)
            first.fecha_hora = datetime(2020, 1, 1, 0, 0, 30, tzinfo=UTC)
            oldest = add_order(db, estado="Nuevo", fecha_hora=datetime(2020, 1, 1, tzinfo=UTC))
            same = add_order(db, estado="Nuevo", fecha_hora=oldest.fecha_hora)
            expected = [oldest.id_pedido, same.id_pedido, 1]
            db.commit()
        response = self.client.post(BASE + "/prioridades", headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        # Si el instante cae en la segunda mitad del minuto, el más antiguo gana también por T.
        self.assertEqual([row["id_pedido"] for row in response.json()["pedidos"]], expected)
        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(Pedido, 1).puntaje_prioridad)
            self.assertIn("G", db.get(Pedido, 1).factores_prioridad)
            self.assertIsNone(db.get(Pedido, 2).puntaje_prioridad)
            db.get(Pedido, 1).distancia_km = Decimal("50")
            db.commit()
        again = self.client.post(BASE + "/prioridades", headers=HEADERS)
        row = next(row for row in again.json()["pedidos"] if row["id_pedido"] == 1)
        self.assertEqual(Decimal(row["factores_prioridad"]["D"]), 0)

    def test_terminal_orders_are_excluded_and_permissions_are_enforced(self):
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = "Entregado"
            db.commit()
        self.assertEqual(self.client.post(BASE + "/prioridades", headers=HEADERS).json()["pedidos"], [])
        self.assertEqual(self.client.post("/api/restaurantes/2/prioridades", headers=HEADERS).status_code, 403)
        self.assertEqual(self.client.post(BASE + "/prioridades").status_code, 403)
        for user in (3, 5, 8):
            self.sign_in(user)
            self.assertEqual(self.client.post(BASE + "/prioridades", headers=HEADERS).status_code, 403)

    def test_distance_is_scoped_traced_and_recalculates_priority(self):
        response = self.client.put(BASE + "/pedidos/1/distancia", headers=HEADERS, json={"distancia_km": "3.125"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["historial"]), 1)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Pedido, 1).distancia_km, Decimal("3.125"))
            self.assertEqual(Decimal(db.get(Pedido, 1).factores_prioridad["D"]), Decimal("6.875"))
        self.assertEqual(self.client.put(BASE + "/pedidos/2/distancia", headers=HEADERS, json={"distancia_km": "1"}).status_code, 404)
        for value in ("-1", "NaN", "1.0001"):
            self.assertEqual(self.client.put(BASE + "/pedidos/1/distancia", headers=HEADERS, json={"distancia_km": value}).status_code, 422)


class DeliveryTests(unittest.TestCase):
    setUp = PriorityTests.setUp
    configure_client = PriorityTests.configure_client
    sign_in = PriorityTests.sign_in

    def make_delivery(self, *, order=1, courier=1, state="Asignado"):
        with Session(self.engine) as db:
            db.get(Pedido, order).estado = state
            delivery = Entrega(id_pedido=order, id_repartidor=courier, estado=state, costo_repartidor=Decimal("12.34"))
            db.add(delivery); db.flush()
            id = delivery.id_entrega
            db.commit()
        return id

    def test_selection_uses_load_then_success_rate_then_name_and_ignores_other_restaurant(self):
        with Session(self.engine) as db:
            db.get(Usuario, 5).nombre = "Zeta"
            db.get(Usuario, 9).nombre = "Alfa"
            db.commit()
        def first():
            with Session(self.engine) as db:
                rows = ranked_couriers(db, 1)
                return rows[0][0].id_repartidor if rows else None
        self.assertEqual(first(), 3)
        self.make_delivery(state="Entregado")
        self.assertEqual(first(), 1)
        with Session(self.engine) as db:
            active = add_order(db)
            active_id = active.id_pedido
            db.commit()
        self.make_delivery(order=active_id)
        self.assertEqual(first(), 3)
        with Session(self.engine) as db:
            db.get(Usuario, 9).activo = False
            db.commit()
        self.assertIsNone(first())

    def test_tracking_ownership_delivery_transitions_and_courier_release(self):
        delivery = self.make_delivery()
        with Session(self.engine) as db:
            db.get(Repartidor, 1).estado_disponibilidad = "Ocupado"
            db.commit()
        self.sign_in(3)
        self.assertEqual(self.client.get("/api/pedidos/1/seguimiento").status_code, 200)
        self.sign_in(4)
        self.assertEqual(self.client.get("/api/pedidos/1/seguimiento").status_code, 404)
        self.sign_in(9)
        self.assertEqual(self.client.get("/api/pedidos/1/seguimiento").status_code, 404)
        self.assertEqual(self.client.put(f"/api/entregas/{delivery}/estado", headers=HEADERS, json={"estado": "En camino"}).status_code, 404)
        self.sign_in(5)
        self.assertEqual(len(self.client.get("/api/entregas").json()), 1)
        for state, expected in (("Entregado", 409), ("En camino", 200), ("En camino", 200),
                                ("Entregado", 200), ("Entregado", 200), ("En camino", 409)):
            response = self.client.put(f"/api/entregas/{delivery}/estado", headers=HEADERS, json={"estado": state})
            self.assertEqual(response.status_code, expected, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Pedido, 1).estado, "Entregado")
            self.assertEqual(db.get(Entrega, delivery).estado, "Entregado")
            self.assertEqual(db.get(Repartidor, 1).estado_disponibilidad, "Disponible")
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialRepartidor)), 1)

    def test_staff_cannot_manage_delivery_and_distances_lock_after_assignment(self):
        delivery = self.make_delivery()
        self.assertEqual(self.client.put(f"/api/entregas/{delivery}/estado", headers=HEADERS, json={"estado": "En camino"}).status_code, 403)
        self.assertEqual(self.client.put(BASE + "/pedidos/1/distancia", headers=HEADERS, json={"distancia_km": "3"}).status_code, 409)
        self.sign_in(2)
        self.assertEqual(self.client.get("/api/entregas").json(), [])
        self.assertEqual(self.client.get("/api/pedidos/1/seguimiento").status_code, 404)
        self.sign_in(8)
        self.assertEqual(self.client.get("/api/pedidos/1/seguimiento").status_code, 403)

    def test_failed_delivery_and_no_available_override_when_manually_unavailable(self):
        delivery = self.make_delivery(state="En camino")
        with Session(self.engine) as db:
            db.get(Repartidor, 1).estado_disponibilidad = "No disponible"
            db.commit()
        self.sign_in(5)
        response = self.client.put(f"/api/entregas/{delivery}/estado", headers=HEADERS, json={"estado": "No entregado"})
        self.assertEqual(response.status_code, 200, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Repartidor, 1).estado_disponibilidad, "No disponible")

    def test_failed_history_write_rolls_back_delivery_and_order_state(self):
        delivery = self.make_delivery()
        self.sign_in(5)
        def fail(*args):
            raise IntegrityError("fixture", {}, Exception("synthetic failure"))
        event.listen(HistorialPedido, "before_insert", fail)
        try:
            response = self.client.put(f"/api/entregas/{delivery}/estado", headers=HEADERS, json={"estado": "En camino"})
        finally:
            event.remove(HistorialPedido, "before_insert", fail)
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(Pedido, 1).estado, "Asignado")
            self.assertEqual(db.get(Entrega, delivery).estado, "Asignado")


class AssignmentTests(unittest.TestCase):
    setUp = PriorityTests.setUp
    configure_client = PriorityTests.configure_client
    sign_in = PriorityTests.sign_in

    def assign(self):
        return self.client.post(BASE + "/entregas/asignar", headers=HEADERS)

    def test_assignment_uses_ready_queue_persists_exact_cost_and_is_not_duplicated(self):
        with Session(self.engine) as db:
            order = db.get(Pedido, 1)
            order.estado = "Listo"
            order.distancia_km = Decimal("3.125")
            restaurant = db.get(Restaurante, 1)
            restaurant.costo_fijo_entrega = Decimal("100")
            restaurant.costo_por_km = Decimal("0.20")
            important = add_order(db, importe_total=Decimal("10000"), costo_total=Decimal("100"))
            important_id = important.id_pedido
            db.commit()
        response = self.assign()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([row["id_pedido"] for row in response.json()["entregas"]], [important_id, 1])
        self.assertEqual([row["id_repartidor"] for row in response.json()["entregas"]], [1, 3])
        self.assertEqual(response.json()["pendientes"], 0)
        self.assertEqual(self.assign().json(), {"entregas": [], "pendientes": 0})
        with Session(self.engine) as db:
            cost = db.scalar(select(Entrega.costo_repartidor).where(Entrega.id_pedido == 1))
            self.assertEqual(cost, Decimal("100.63"))
            self.assertEqual(db.get(Pedido, 1).importe_total, Decimal("100"))
            self.assertEqual(db.get(Pedido, 1).costo_total, Decimal("10"))
            self.assertEqual(db.get(Pedido, 2).estado, "Nuevo")
            self.assertEqual(db.get(Repartidor, 1).estado_disponibilidad, "Ocupado")
            self.assertEqual(db.scalar(select(func.count()).select_from(Entrega)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialRepartidor)), 2)

    def test_no_couriers_keeps_ready_orders_pending_and_permissions_are_enforced(self):
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = "Listo"
            for id in (1, 3):
                db.get(Repartidor, id).estado_disponibilidad = "No disponible"
            add_order(db, estado="En preparación")
            db.commit()
        response = self.assign()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"entregas": [], "pendientes": 1})
        self.assertEqual(self.client.post("/api/restaurantes/2/entregas/asignar", headers=HEADERS).status_code, 403)
        self.assertEqual(self.client.post(BASE + "/entregas/asignar").status_code, 403)
        for user in (3, 5, 8):
            self.sign_in(user)
            self.assertEqual(self.assign().status_code, 403)

    def test_prepare_assign_deliver_and_client_tracking_end_to_end(self):
        path = BASE + "/pedidos/1/preparacion"
        for state in ("En preparación", "Listo"):
            version = self.client.get(path).json()["version"]
            response = self.client.put(path, headers=HEADERS, json={"estado": state, "version": version})
            self.assertEqual(response.status_code, 200, response.text)
        assigned = self.assign()
        self.assertEqual(assigned.status_code, 200, assigned.text)
        delivery = assigned.json()["entregas"][0]
        self.assertEqual(delivery["id_repartidor"], 1)
        self.assertEqual(self.client.put(path, headers=HEADERS,
                                       json={"estado": "En preparación", "version": 0, "nueva_preparacion": True, "motivo": "Intento"}).status_code, 409)
        self.sign_in(5)
        for state in ("En camino", "Entregado"):
            result = self.client.put(f'/api/entregas/{delivery["id_entrega"]}/estado', headers=HEADERS, json={"estado": state})
            self.assertEqual(result.status_code, 200, result.text)
        self.sign_in(3)
        track = self.client.get("/api/pedidos/1/seguimiento")
        self.assertEqual(track.status_code, 200, track.text)
        self.assertEqual(track.json()["estado_pedido"], "Entregado")
        self.assertEqual([event["estado"] for event in track.json()["historial"]],
                         ["En preparación", "Listo", "Asignado", "En camino", "Entregado"])
        with Session(self.engine) as db:
            self.assertEqual(db.get(Insumo, 1).stock_actual, Decimal("19.8"))
            self.assertEqual(db.get(Repartidor, 1).estado_disponibilidad, "Disponible")

    def test_assignment_failure_rolls_back_delivery_history_order_and_availability(self):
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = "Listo"
            db.commit()
        def fail(*args):
            raise IntegrityError("fixture", {}, Exception("synthetic failure"))
        event.listen(Entrega, "before_insert", fail)
        try:
            response = self.assign()
        finally:
            event.remove(Entrega, "before_insert", fail)
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Entrega)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialPedido)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(HistorialRepartidor)), 0)
            self.assertEqual(db.get(Pedido, 1).estado, "Listo")
            self.assertEqual(db.get(Repartidor, 1).estado_disponibilidad, "Disponible")

    def test_cost_overflow_rejects_assignment_without_partial_writes(self):
        with Session(self.engine) as db:
            db.get(Pedido, 1).estado = "Listo"
            db.get(Pedido, 1).distancia_km = Decimal("2")
            db.get(Restaurante, 1).costo_por_km = Decimal("6000000000000000")
            db.commit()
        response = self.assign()
        self.assertEqual(response.status_code, 422, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Entrega)), 0)
            self.assertEqual(db.get(Pedido, 1).estado, "Listo")
