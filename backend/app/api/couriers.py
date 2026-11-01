from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.auth.dependencies import DB, require_restaurant, require_roles
from app.couriers.schemas import AvailabilityInput, CourierOutput, CourierPage
from app.couriers.service import list_couriers, update_availability
from app.couriers.schemas import CourierInput, RatesInput, RatesOutput
from app.couriers.service import create_courier, restaurant_rates
from app.couriers.earnings import daily_earnings
from app.db.models import Usuario

router = APIRouter(tags=["Repartidores"])
Staff = Annotated[Usuario, Depends(require_restaurant("personal", "propietario"))]
Courier = Annotated[Usuario, Depends(require_roles("repartidor"))]
PositiveId = Annotated[int, Path(gt=0)]
Owner = Annotated[Usuario, Depends(require_restaurant("propietario"))]


@router.post("/restaurantes/{id_restaurante}/repartidores", response_model=CourierOutput, status_code=201)
def add_courier(id_restaurante: PositiveId, data: CourierInput, db: DB, user: Owner):
    return create_courier(db, user, data)


@router.get("/restaurantes/{id_restaurante}/tarifas", response_model=RatesOutput)
def get_rates(id_restaurante: PositiveId, db: DB, user: Owner):
    return restaurant_rates(db, id_restaurante)


@router.put("/restaurantes/{id_restaurante}/tarifas", response_model=RatesOutput)
def set_rates(id_restaurante: PositiveId, data: RatesInput, db: DB, user: Owner):
    return restaurant_rates(db, id_restaurante, data)


@router.get("/restaurantes/{id_restaurante}/repartidores", response_model=CourierPage)
def restaurant_couriers(id_restaurante: PositiveId, db: DB, user: Staff):
    return list_couriers(db, user)


@router.put("/restaurantes/{id_restaurante}/repartidores/{id_repartidor}", response_model=CourierOutput)
def set_availability(id_restaurante: PositiveId, id_repartidor: PositiveId, data: AvailabilityInput, db: DB, user: Staff):
    return update_availability(db, user, id_repartidor, data)


@router.get("/repartidores/me", response_model=CourierPage)
def own_availability(db: DB, user: Courier):
    return list_couriers(db, user)


@router.get("/repartidores/me/resumen-diario")
def own_earnings(db: DB, user: Courier):
    return daily_earnings(db, user)


@router.put("/repartidores/me", response_model=CourierOutput)
def set_own_availability(data: AvailabilityInput, db: DB, user: Courier):
    return update_availability(db, user, None, data)
