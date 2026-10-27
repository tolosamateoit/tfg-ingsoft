from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.analytics.schemas import PeriodInput
from app.auth.dependencies import DB, require_restaurant
from app.dashboard.service import DashboardOutput, dashboard
from app.db.models import Usuario

router = APIRouter(tags=["Dashboard"])
Staff = Annotated[Usuario, Depends(require_restaurant("personal", "propietario"))]


@router.post("/restaurantes/{id_restaurante}/dashboard", response_model=DashboardOutput)
def restaurant_dashboard(id_restaurante: Annotated[int, Path(gt=0)], data: PeriodInput, db: DB, user: Staff):
    return dashboard(db, user, id_restaurante, data)
