from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.auth.dependencies import DB, require_restaurant, require_roles
from app.couriers.schemas import AvailabilityInput, CourierOutput, CourierPage
from app.couriers.service import list_couriers, update_availability
from app.db.models import Usuario

router = APIRouter(tags=["Repartidores"])
Staff = Annotated[Usuario, Depends(require_restaurant("personal", "propietario"))]
Courier = Annotated[Usuario, Depends(require_roles("repartidor"))]
PositiveId = Annotated[int, Path(gt=0)]


@router.get("/restaurantes/{id_restaurante}/repartidores", response_model=CourierPage)
def restaurant_couriers(id_restaurante: PositiveId, db: DB, user: Staff):
    return list_couriers(db, user)


@router.put("/restaurantes/{id_restaurante}/repartidores/{id_repartidor}", response_model=CourierOutput)
def set_availability(id_restaurante: PositiveId, id_repartidor: PositiveId, data: AvailabilityInput, db: DB, user: Staff):
    return update_availability(db, user, id_repartidor, data)


@router.get("/repartidores/me", response_model=CourierPage)
def own_availability(db: DB, user: Courier):
    return list_couriers(db, user)


@router.put("/repartidores/me", response_model=CourierOutput)
def set_own_availability(data: AvailabilityInput, db: DB, user: Courier):
    return update_availability(db, user, None, data)
