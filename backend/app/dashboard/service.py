from collections import Counter
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.forecast import latest_forecast
from app.analytics.metrics import list_alerts, metrics
from app.analytics.schemas import AlertOutput, ForecastOutput, PeriodInput
from app.auth.service import as_utc
from app.couriers.schemas import CourierPage
from app.couriers.service import list_couriers
from app.db.models import Usuario
from app.logistics.priority import priorities
from app.logistics.schemas import DeliveryOutput, PriorityPage
from app.logistics.service import deliveries
from app.preparation.schemas import StockOutput
from app.preparation.service import stock


class IndicatorSummary(BaseModel):
    inicio: date
    fin: date
    referencia_inicio: date
    referencia_fin: date
    promedios: dict[str, Decimal | None]
    promedios_referencia: dict[str, Decimal | None]
    muestras: dict[str, int]
    muestras_referencia: dict[str, int]


class DashboardOutput(BaseModel):
    id_restaurante: int
    actualizado_en: datetime
    prioridades: PriorityPage
    pedidos_por_estado: dict[str, int]
    entregas_recientes: list[DeliveryOutput]
    stock: list[StockOutput]
    repartidores: CourierPage
    alertas_activas: list[AlertOutput]
    indicadores: IndicatorSummary | None
    prediccion_guardada: ForecastOutput | None


def dashboard(db: Session, user: Usuario, restaurant_id: int, period: PeriodInput) -> DashboardOutput:
    if user.rol == "propietario":
        calculated = metrics(db, user, restaurant_id, period)
        inventory, couriers, alerts = calculated.stock, calculated.repartidores, calculated.alertas
        indicators = IndicatorSummary(**calculated.model_dump(include=set(IndicatorSummary.model_fields)))
        forecast = latest_forecast(db, restaurant_id)
    else:
        inventory, couriers = stock(db, restaurant_id), list_couriers(db, user)
        # Personal recibe incidencias operativas, sin alertas de importes ni predicciones.
        alerts = [alert for alert in list_alerts(db, restaurant_id) if alert.tipo in {"stock", "preparacion", "entrega"}]
        indicators, forecast = None, None
    ordered = priorities(db, restaurant_id)
    return DashboardOutput(id_restaurante=restaurant_id, actualizado_en=as_utc(db.scalar(select(func.now()))),
                           prioridades=ordered, pedidos_por_estado=dict(Counter(order.estado for order in ordered.pedidos)),
                           entregas_recientes=deliveries(db, user, 0), stock=inventory, repartidores=couriers,
                           alertas_activas=[alert for alert in alerts if alert.estado == "Activa"],
                           indicadores=indicators, prediccion_guardada=forecast)
