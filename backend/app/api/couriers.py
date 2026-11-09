from typing import Annotated

from fastapi import APIRouter, Depends, Path, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import select

from app.auth.dependencies import DB, require_restaurant, require_roles
from app.couriers.schemas import AvailabilityInput, CourierOutput, CourierPage
from app.couriers.service import list_couriers, update_availability
from app.couriers.schemas import CourierInput, RatesInput, RatesOutput
from app.couriers.service import create_courier, restaurant_rates
from app.couriers.earnings import daily_earnings
from app.db.models import Usuario, Restaurante
from app.orders.service import lock_order_relations
from app.orders.operating_days import local_today, register_open_days
from app.db.models import DiaOperativo
from app.couriers.performance import performance
from app.db.models import Repartidor
from datetime import date

router = APIRouter(tags=["Repartidores"])
Staff = Annotated[Usuario, Depends(require_restaurant("personal", "propietario"))]
Courier = Annotated[Usuario, Depends(require_roles("repartidor"))]
PositiveId = Annotated[int, Path(gt=0)]
Owner = Annotated[Usuario, Depends(require_restaurant("propietario"))]

class RestaurantStatus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    abierto: StrictBool

@router.get('/restaurantes/{id_restaurante}/estado', response_model=RestaurantStatus)
def get_restaurant_status(id_restaurante: PositiveId, db: DB, user: Owner):
    restaurant = db.get(Restaurante, id_restaurante)
    if restaurant is None:
        raise HTTPException(404, 'Restaurante no disponible.')
    return {'abierto': restaurant.abierto}

@router.put('/restaurantes/{id_restaurante}/estado', response_model=RestaurantStatus)
def set_restaurant_status(id_restaurante: PositiveId, data: RestaurantStatus, db: DB, user: Owner):
    lock_order_relations(db)
    restaurant = db.scalar(select(Restaurante).where(Restaurante.id_restaurante == id_restaurante).with_for_update())
    if restaurant is None:
        raise HTTPException(404, 'Restaurante no disponible.')
    if restaurant.abierto:
        register_open_days(db, restaurant)
    elif data.abierto:
        today = local_today()
        if db.get(DiaOperativo, (id_restaurante, today)) is None:
            db.add(DiaOperativo(id_restaurante=id_restaurante, fecha=today))
    restaurant.abierto = data.abierto
    db.commit()
    return {'abierto': restaurant.abierto}


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

@router.get('/repartidores/me/desempeno')
def own_performance(db: DB, user: Courier, fecha: date | None = None):
    courier = db.scalar(select(Repartidor).where(Repartidor.id_usuario == user.id_usuario))
    if courier is None:
        raise HTTPException(404, 'Repartidor no disponible.')
    return performance(db, user, courier.id_repartidor, fecha)

@router.get('/restaurantes/{id_restaurante}/repartidores/{id_repartidor}/desempeno')
def courier_performance(id_restaurante: PositiveId, id_repartidor: PositiveId, db: DB, user: Owner):
    return performance(db, user, id_repartidor)


@router.put("/repartidores/me", response_model=CourierOutput)
def set_own_availability(data: AvailabilityInput, db: DB, user: Courier):
    return update_availability(db, user, None, data)
