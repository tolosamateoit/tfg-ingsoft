"""Validación integrada sin modificar la base de demostración."""
import json
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.db.engine import build_engine
from app.db.models import Usuario, Pedido, Producto, DetallePedido
from app.analytics.forecast import calculate_forecast
from app.analytics.experiment import forecast_audit


def main():
    engine = build_engine()
    try:
        with Session(engine) as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            owner = db.scalar(select(Usuario).where(Usuario.id_restaurante == 2, Usuario.rol == 'propietario', Usuario.activo.is_(True)))
            assert owner is not None
            result = calculate_forecast(db, owner.id_restaurante)
            assert str(result.fecha_operativa) == '2026-10-31'
            assert len(result.predicciones) == 10
            assert not result.recetas_faltantes
            assert len(result.insumos) == 19
            assert all(str(p.periodo_inicio) == '2026-11-01' and str(p.periodo_fin) == '2026-11-07' for p in result.predicciones)
            assert all(sum(d.cantidad for d in p.dias) == p.demanda_estimada for p in result.predicciones)
            assert all(p.observaciones_evaluadas == 7 for p in result.predicciones)
            own = {
                'pedido': db.execute(select(Pedido.__table__).where(Pedido.id_restaurante == owner.id_restaurante)).mappings().all(),
                'producto': db.execute(select(Producto.__table__).where(Producto.id_restaurante == owner.id_restaurante)).mappings().all(),
                'detalle_pedido': db.execute(select(DetallePedido.__table__).join(Pedido).where(Pedido.id_restaurante == owner.id_restaurante)).mappings().all(),
            }
            audit = forecast_audit(own, result, result.fecha_operativa)
            assert len(audit['products']) == 10
            print(json.dumps(result.model_dump(mode='json'), ensure_ascii=True, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
