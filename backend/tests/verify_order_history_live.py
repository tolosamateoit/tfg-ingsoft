"""Verificación explícita de Supabase en transacción READ ONLY; no hace login."""

import argparse
import json

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.engine import build_engine
from app.db.models import DetallePedido, Pedido, Producto, Usuario
from app.logistics.service import deliveries, tracking
from app.orders.operational_date import OPERATIONAL_ZONE
from app.orders.service import list_orders, read_order


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restaurant-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, required=True)
    args = parser.parse_args()
    engine = build_engine()
    try:
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            user = db.get(Usuario, args.user_id)
            assert user and user.activo and user.id_restaurante == args.restaurant_id and user.rol in {"propietario", "personal"}
            initial = list_orders(db, user, 100, 0)
            rows = []
            for offset in range(0, initial.total, 100):
                page = initial if offset == 0 else list_orders(db, user, 100, offset)
                rows.extend(page.pedidos)
            expected_ids = list(db.scalars(select(Pedido.id_pedido).where(Pedido.id_restaurante == args.restaurant_id)
                                           .order_by(Pedido.fecha_hora.desc(), Pedido.id_pedido.desc())))
            assert [r.id_pedido for r in rows] == expected_ids
            assert len(rows) == len({r.id_pedido for r in rows}) == initial.total
            details = db.execute(select(DetallePedido.id_pedido, DetallePedido.cantidad, Producto.nombre)
                .join(Pedido, Pedido.id_pedido == DetallePedido.id_pedido)
                .join(Producto, Producto.id_producto == DetallePedido.id_producto)
                .where(Pedido.id_restaurante == args.restaurant_id).order_by(DetallePedido.id_detalle)).all()
            parts = {}
            for oid, qty, name in details:
                parts.setdefault(oid, []).append(f"{qty} × {name}")
            assert all(r.resumen_productos == ", ".join(parts[r.id_pedido]) for r in rows)
            day = list_orders(db, user, 100, 0, "dia")
            assert day.total == sum(r.fecha_hora.astimezone(OPERATIONAL_ZONE).date() == day.fecha_operativa for r in rows)
            assert day.total <= 100  # dataset actual; fallar si la comprobación requiere más páginas
            assert all(r.fecha_hora.astimezone(OPERATIONAL_ZONE).date() == day.fecha_operativa for r in day.pedidos)
            found = {}
            for oid in (1, 2):
                if oid in expected_ids:
                    detail = read_order(db, user, oid)
                    follow = tracking(db, user, oid)
                    assert detail.id_restaurante == args.restaurant_id and detail.estado == follow.estado_pedido
                    found[str(oid)] = dict(accessible=True, history_page=expected_ids.index(oid) // 20 + 1)
            by_id = {r.id_pedido: r for r in rows}
            delivery_rows = deliveries(db, user, 0)
            for delivery in delivery_rows:
                order = by_id[delivery.id_pedido]
                assert order.id_entrega == delivery.id_entrega and order.repartidor == delivery.repartidor
                assert order.resumen_productos == delivery.resumen_productos
                assert order.estado == delivery.estado
            print(json.dumps(dict(mode="READ ONLY", restaurant_id=args.restaurant_id,
                history_total=len(rows), pages_of_20=(len(rows) + 19)//20, day_total=day.total,
                operational_date=str(day.fecha_operativa), old_orders=found,
                summaries_checked=len(rows), deliveries_checked=len(delivery_rows), validation="passed"), indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
