"""Ranking de la demo contrastado sin escribir puntajes, estados ni historial."""
import json
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.auth.service import as_utc
from app.db.engine import build_engine
from app.db.models import Pedido, HistorialPedido, Usuario
from app.logistics.priority import PENDING, priority_preview
from app.orders.distance import unconfirmed_distances


def main():
    engine = build_engine()
    try:
        with Session(engine) as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            owner = db.scalar(select(Usuario).where(Usuario.id_restaurante == 2, Usuario.rol == 'propietario', Usuario.activo.is_(True)))
            assert owner is not None
            page = priority_preview(db, owner.id_restaurante)
            assert not db.dirty
            orders = db.scalars(select(Pedido).where(Pedido.id_restaurante == owner.id_restaurante, Pedido.estado.in_(PENDING))).all()
            unknown = unconfirmed_distances(db, [o.id_pedido for o in orders])
            scores = {}
            for o in orders:
                wait = max(0, int((as_utc(page.calculada_en) - as_utc(o.fecha_hora)).total_seconds() // 60))
                distance = max(Decimal(0), 10 - o.distancia_km) if o.id_pedido not in unknown else Decimal(0)
                margin = max(Decimal(0), (o.importe_total - o.costo_total) / 1000)
                scores[o.id_pedido] = wait + distance + margin
            expected = sorted(orders, key=lambda o: (-scores[o.id_pedido], as_utc(o.fecha_hora), o.id_pedido))
            assert [r.id_pedido for r in page.pedidos] == [o.id_pedido for o in expected]
            assert [r.posicion for r in page.pedidos] == list(range(1,len(orders)+1))
            assert all(r.puntaje_prioridad == scores[r.id_pedido] for r in page.pedidos)
            print(json.dumps(dict(mode='READ ONLY', restaurant_id=owner.id_restaurante, pending=len(orders),
                ranking_checked=len(page.pedidos), validation='passed'), indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
