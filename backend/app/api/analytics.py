from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from app.analytics.forecast import day_forecast, generate_forecast, latest_forecast
from app.analytics.schemas import AlertPage, DayForecastOutput, ForecastOutput, MetricsOutput, PeriodInput
from app.analytics.metrics import metrics
from app.analytics.alerts import alert_page
from app.analytics.operational import OperationalDashboard, operational_dashboard
from app.auth.dependencies import DB, require_restaurant
from app.db.models import Usuario

router = APIRouter(prefix="/restaurantes/{id_restaurante}", tags=["Predicción e indicadores"])
Owner = Annotated[Usuario, Depends(require_restaurant("propietario"))]
PositiveId = Annotated[int, Path(gt=0)]


@router.get('/predicciones/diaria', response_model=DayForecastOutput)
def daily_forecast(id_restaurante: PositiveId, db: DB, user: Owner, fecha: date | None = None):
    return day_forecast(db, user.id_restaurante, fecha)


@router.post("/predicciones", response_model=ForecastOutput)
def forecast(id_restaurante: PositiveId, db: DB, user: Owner):
    return generate_forecast(db, id_restaurante)


@router.get("/predicciones", response_model=ForecastOutput)
def saved_forecast(id_restaurante: PositiveId, db: DB, user: Owner):
    return latest_forecast(db, id_restaurante)


@router.post("/indicadores", response_model=MetricsOutput)
def calculate_metrics(id_restaurante: PositiveId, data: PeriodInput, db: DB, user: Owner):
    return metrics(db, user, id_restaurante, data)


@router.get('/indicadores', response_model=OperationalDashboard)
def daily_indicators(id_restaurante: PositiveId, db: DB, user: Owner, fecha: date | None = None):
    return operational_dashboard(db, user, id_restaurante, fecha)


@router.get("/alertas", response_model=AlertPage)
def alerts(id_restaurante: PositiveId, db: DB, user: Owner,
           limit: Annotated[int, Query(ge=1, le=100)] = 25,
           offset: Annotated[int, Query(ge=0)] = 0,
           tipo: Literal["importe", "preparacion", "entrega", "stock"] | None = None,
           estado: Literal["Activa", "Resuelta"] | None = None,
           severidad: Literal["critica", "advertencia"] | None = None):
    return alert_page(db, id_restaurante, limit=limit, offset=offset,
                      tipo=tipo, estado=estado, severidad=severidad)
