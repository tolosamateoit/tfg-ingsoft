"""HU-03: oferta del restaurante y pedidos propios/del restaurante autorizado."""

from typing import Annotated, Literal
from datetime import date

from fastapi import APIRouter, Depends, Path, Query

from app.auth.dependencies import CurrentUser, DB, require_roles, require_restaurant
from app.db.models import Usuario
from app.orders.schemas import CustomerMenuOutput, OrderInput, OrderOutput, OrderPage, RestaurantOutput
from app.orders.service import create_order, customer_menu, customer_restaurants, list_orders, read_order
from app.orders.operational import OperatingDay, operating_day

router = APIRouter(tags=["Pedidos"])
Customer = Annotated[Usuario, Depends(require_roles("cliente"))]
PositiveId = Annotated[int, Path(gt=0)]
Staff = Annotated[Usuario, Depends(require_restaurant("personal", "propietario"))]
OrderUser = Annotated[Usuario, Depends(require_roles("cliente", "personal", "propietario"))]


@router.get('/restaurantes/{id_restaurante}/pedidos/operacion', response_model=OperatingDay)
def daily_operation(id_restaurante: PositiveId, db: DB, user: Staff,
                    limit: Annotated[int, Query(ge=1, le=100)] = 20,
                    offset: Annotated[int, Query(ge=0)] = 0):
    return operating_day(db, user, id_restaurante, limit, offset)


@router.post("/restaurantes/{id_restaurante}/pedidos", response_model=OrderOutput, status_code=201)
def register_order(id_restaurante: PositiveId, data: OrderInput, db: DB, user: OrderUser):
    return create_order(db, user, id_restaurante, data)


@router.get("/restaurantes", response_model=list[RestaurantOutput])
def restaurants(db: DB, user: Customer):
    return customer_restaurants(db)


@router.get("/restaurantes/{id_restaurante}/menu", response_model=CustomerMenuOutput)
def menu(id_restaurante: PositiveId, db: DB, user: Customer):
    return customer_menu(db, id_restaurante)


@router.get("/pedidos", response_model=OrderPage)
def orders(db: DB, user: CurrentUser,
           limit: Annotated[int, Query(ge=1, le=100)] = 20,
           offset: Annotated[int, Query(ge=0)] = 0,
           periodo: Literal["dia", "historial"] = "historial", fecha: date | None = None):
    return list_orders(db, user, limit, offset, periodo, fecha)


@router.get("/pedidos/{id_pedido}", response_model=OrderOutput)
def order(id_pedido: PositiveId, db: DB, user: CurrentUser):
    return read_order(db, user, id_pedido)
