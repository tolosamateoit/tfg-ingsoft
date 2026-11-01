"""Indicadores de Supabase contrastados con SQL; transacción READ ONLY."""
import json
from decimal import Decimal
from time import perf_counter
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session
from app.analytics.operational import operational_dashboard
from app.db.engine import build_engine
from app.db.models import Pedido, Usuario
from app.orders.operational_date import operational_day_bounds


def main():
    engine = build_engine()
    try:
        with Session(engine) as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            owner = db.scalar(select(Usuario).where(Usuario.id_restaurante == 2, Usuario.rol == 'propietario', Usuario.activo.is_(True)))
            assert owner is not None
            began = perf_counter()
            result = operational_dashboard(db, owner, owner.id_restaurante)
            elapsed = perf_counter() - began
            start, end = operational_day_bounds(result.fecha)
            counts = db.execute(select(func.count(), func.sum(case((Pedido.estado == 'Entregado', 1), else_=0)),
                func.sum(case((Pedido.estado == 'Entregado', Pedido.importe_total), else_=Decimal(0))))
                .where(Pedido.id_restaurante == owner.id_restaurante, Pedido.fecha_hora >= start, Pedido.fecha_hora < end)).one()
            assert result.pedidos == counts[0]
            assert result.pedidos_entregados == counts[1]
            assert result.ventas == counts[2]
            assert result.ticket_promedio == (result.ventas / result.pedidos_entregados).quantize(Decimal('.01'))
            assert len(result.evolucion) == 7
            assert result.fecha_stock == result.fecha_operativa
            assert len(result.alertas) <= 6
            print(json.dumps(dict(mode='READ ONLY', elapsed_seconds=round(elapsed, 2), validation='passed',
                dashboard=result.model_dump(mode='json')), ensure_ascii=True, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
