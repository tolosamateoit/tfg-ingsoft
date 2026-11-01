"""Consulta paginada de alertas existentes; no ejecuta los motores ni escribe datos."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.analytics.schemas import AlertOutput, AlertPage
from app.db.models import Alerta


def alert_page(db: Session, restaurant: int, *, limit: int = 25, offset: int = 0,
               tipo: str | None = None, estado: str | None = None,
               severidad: str | None = None) -> AlertPage:
    conditions = [Alerta.id_restaurante == restaurant]
    if tipo:
        conditions.append(Alerta.tipo == tipo)
    if estado:
        conditions.append(Alerta.estado == estado)
    critical = or_(and_(Alerta.tipo == "stock", Alerta.valor_observado < 0),
                   Alerta.valor_observado > Alerta.valor_referencia * 2)
    if severidad:
        conditions.append(critical if severidad == "critica" else ~critical)
    total = db.scalar(select(func.count()).select_from(Alerta).where(*conditions))
    rows = db.scalars(select(Alerta).where(*conditions)
                      .order_by(Alerta.fecha_hora.desc(), Alerta.id_alerta.desc())
                      .limit(limit).offset(offset)).all()
    output = []
    for row in rows:
        item = AlertOutput.model_validate(row)
        item.descripcion = row.descripcion.partition(" | ")[2] or row.descripcion
        output.append(item)
    return AlertPage(alertas=output, total=total, limit=limit, offset=offset)
