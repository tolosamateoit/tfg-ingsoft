"""Integración de Pedidos del día en Supabase, exclusivamente READ ONLY."""
import json
from time import perf_counter
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.db.engine import build_engine
from app.db.models import Pedido,Usuario,Entrega
from app.orders.operational import operating_day
from app.orders.operational_date import operational_day_bounds
from app.orders.distance import unconfirmed_distances
from app.logistics.priority import ACTIVE,PENDING


def main():
    engine=build_engine()
    try:
        with Session(engine) as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            user=db.scalar(select(Usuario).where(Usuario.id_restaurante==2,Usuario.rol=='propietario',Usuario.activo.is_(True)))
            assert user is not None
            began=perf_counter()
            result=operating_day(db,user,user.id_restaurante)
            elapsed=perf_counter()-began
            start,end=operational_day_bounds(result.fecha_operativa)
            rows=db.scalars(select(Pedido).where(Pedido.id_restaurante==user.id_restaurante,Pedido.fecha_hora>=start,Pedido.fecha_hora<end)).all()
            assert {r.id_pedido for r in result.activos}=={r.id_pedido for r in rows if r.estado in PENDING}
            assert {r.id_pedido for r in result.listos}=={r.id_pedido for r in rows if r.estado=='Listo'}
            assert {r.id_pedido for r in result.en_entrega}=={r.id_pedido for r in rows if r.estado in ['Asignado','En camino']}
            assert result.total_finalizados==sum(r.estado not in ACTIVE for r in rows)
            assert [r.prioridad.posicion for r in result.activos]==list(range(1,len(result.activos)+1))
            unknown=unconfirmed_distances(db,[r.id_pedido for r in rows])
            assert all(r.distancia_km is None for r in result.activos if r.id_pedido in unknown)
            assert all(r.prioridad.factores_prioridad['D'] is None for r in result.activos if r.id_pedido in unknown)
            assert not db.dirty
            print(json.dumps(dict(mode='READ ONLY',validation='passed',elapsed_seconds=round(elapsed,2),
                operational_date=str(result.fecha_operativa),orders=len(rows),active=len(result.activos),ready=len(result.listos),
                deliveries=len(result.en_entrega),finished=result.total_finalizados,unknown_distances=len(unknown),
                available_couriers=len(result.repartidores)),indent=2))
    finally:
        engine.dispose()


if __name__=='__main__':
    main()
