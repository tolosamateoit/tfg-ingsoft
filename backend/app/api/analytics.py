from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.analytics.forecast import generate_forecast, latest_forecast
from app.analytics.schemas import AlertOutput, ForecastOutput, MetricsOutput, PeriodInput
from app.analytics.metrics import list_alerts, metrics
from app.auth.dependencies import DB, require_restaurant
from app.db.models import Usuario

router = APIRouter(prefix="/restaurantes/{id_restaurante}", tags=["Predicción e indicadores"])
Owner = Annotated[Usuario, Depends(require_restaurant("propietario"))]
PositiveId = Annotated[int, Path(gt=0)]


@router.post("/predicciones", response_model=ForecastOutput)
def forecast(id_restaurante: PositiveId, db: DB, user: Owner):
    return generate_forecast(db, id_restaurante)


@router.get("/predicciones", response_model=ForecastOutput)
def saved_forecast(id_restaurante: PositiveId, db: DB, user: Owner):
    return latest_forecast(db, id_restaurante)


@router.post("/indicadores", response_model=MetricsOutput)
def calculate_metrics(id_restaurante: PositiveId, data: PeriodInput, db: DB, user: Owner):
    return metrics(db, user, id_restaurante, data)


@router.get("/alertas", response_model=list[AlertOutput])
def alerts(id_restaurante: PositiveId, db: DB, user: Owner):
    return list_alerts(db, id_restaurante)
