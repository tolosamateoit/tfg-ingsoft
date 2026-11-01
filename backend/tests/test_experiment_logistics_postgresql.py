"""Evidencia controlada de HU-06/HU-07; el runner admite solo PostgreSQL local."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import unittest

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Entrega, Pedido, Repartidor, Restaurante, Usuario
from app.logistics.priority import calculate, priorities
from app.logistics.service import assign_ready_orders, delivery_cost, ranked_couriers
from tests import test_orders_postgresql, test_logistics


@unittest.skipUnless(os.environ.get("TFG_TEST_POSTGRES_DSN"), "Solo PostgreSQL local descartable")
class ExperimentalLogisticsTests(unittest.TestCase):
    setUp = test_orders_postgresql.OrderReadPostgreSQLTests.setUp
    drop_test_tables = test_orders_postgresql.OrderReadPostgreSQLTests.drop_test_tables

    def configure_client(self):
        pass

    def test_formula_ties_ranking_assignment_and_rounding(self):
        fixed = datetime(2026, 10, 31, 15, tzinfo=UTC)
        example = Pedido(fecha_hora=fixed - timedelta(minutes=10001, seconds=59), distancia_km=Decimal("3.25"),
                         importe_total=Decimal("10000.12"), costo_total=Decimal("5500.01"))
        calculate(example, fixed)
        self.assertEqual(example.puntaje_prioridad, Decimal("10012.25011"))
        report = dict(kind="Prueba aislada; PostgreSQL local descartable", formula=dict(at=fixed.isoformat(),
            age="10001 min 59 s", distance="3.25", amount="10000.12", cost="5500.01",
            factors=example.factores_prioridad, priority=str(example.puntaje_prioridad)))
        with Session(self.engine) as db:
            db.execute(delete(Entrega))
            now = db.scalar(select(func.now()))
            newest = db.get(Pedido, 1)
            newest.estado = "Listo"; newest.fecha_hora = now - timedelta(minutes=10, seconds=5)
            older = test_logistics.add_order(db, fecha_hora=now - timedelta(minutes=10, seconds=10))
            same = test_logistics.add_order(db, fecha_hora=older.fecha_hora)
            expected = [older.id_pedido, same.id_pedido, newest.id_pedido]
            for order in (newest, older, same):
                order.distancia_km = Decimal("2.55")
            db.get(Usuario, 5).nombre = "Bruno Silva"
            db.get(Usuario, 9).nombre = "Ana Ruiz"
            restaurant = db.get(Restaurante, 1)
            restaurant.costo_fijo_entrega = Decimal("100")
            restaurant.costo_por_km = Decimal(".10")
            db.commit()
            queue = priorities(db, 1)
            self.assertEqual([row.id_pedido for row in queue.pedidos], expected)
            self.assertEqual(len({row.puntaje_prioridad for row in queue.pedidos}), 1)
            report["ties"] = [dict(order_id=row.id_pedido, created=row.fecha_hora.isoformat(), factors=row.factores_prioridad,
                                   priority=str(row.puntaje_prioridad)) for row in queue.pedidos]
            def ranking():
                return [courier.id_repartidor for courier, user in ranked_couriers(db, 1)]
            alphabetical = ranking()
            self.assertEqual(alphabetical, [3, 1])
            for courier, state in ((1, "Entregado"), (3, "No entregado")):
                completed = test_logistics.add_order(db, estado=state)
                db.add(Entrega(id_pedido=completed.id_pedido, id_repartidor=courier, estado=state, costo_repartidor=100))
            db.flush()
            success = ranking()
            self.assertEqual(success, [1, 3])
            working = test_logistics.add_order(db, estado="Asignado")
            db.add(Entrega(id_pedido=working.id_pedido, id_repartidor=1, estado="Asignado", costo_repartidor=100))
            db.flush()
            load = ranking()
            self.assertEqual(load, [3, 1])
            db.get(Usuario, 9).activo = False
            db.flush()
            inactive = ranking()
            self.assertEqual(inactive, [1])
            db.get(Usuario, 9).activo = True
            db.flush()
            db.get(Repartidor, 1).estado_disponibilidad = "No disponible"
            db.flush()
            unavailable = ranking()
            self.assertEqual(unavailable, [3])
            db.get(Repartidor, 1).estado_disponibilidad = "Disponible"
            db.commit()
            report["ranking"] = dict(alphabetical=alphabetical, success_rate=success, workload=load,
                inactive_excluded=inactive, unavailable_excluded=unavailable, foreign_courier_id=2,
                couriers=[dict(id=1, name="Bruno Silva", active_load=1, successes=1, finished=1),
                          dict(id=3, name="Ana Ruiz", active_load=0, successes=0, finished=1)])
            user = db.get(Usuario, 1)
            assigned = assign_ready_orders(db, user, 1)
            self.assertEqual([row.id_pedido for row in assigned.entregas], expected[:2])
            self.assertEqual([row.id_repartidor for row in assigned.entregas], [3, 1])
            self.assertEqual(assigned.pendientes, 1)
            costs = list(db.scalars(select(Entrega.costo_repartidor).where(Entrega.id_pedido.in_(expected[:2]))))
            self.assertEqual(costs, [Decimal("100.26")] * 2)
            before = db.scalar(select(func.count()).select_from(Entrega))
            retried = assign_ready_orders(db, user, 1)
            self.assertEqual(len(retried.entregas), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Entrega)), before)
            report["assignment"] = dict(orders=[row.id_pedido for row in assigned.entregas],
                couriers=[row.id_repartidor for row in assigned.entregas], pending=assigned.pendientes,
                costs=[str(cost) for cost in costs], fixed="100.00", per_km="0.10", distance="2.55",
                exact_cost="100.255", rounding="ROUND_HALF_UP → 100.26", retry_new_deliveries=0)
        destination = os.environ.get("TFG_EXPERIMENT_LOGISTICS_OUTPUT")
        if destination:
            Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
