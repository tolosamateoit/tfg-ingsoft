"""HU-03: oferta del restaurante y pedidos propios/del restaurante autorizado."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.auth.dependencies import CurrentUser, DB, require_roles
from app.db.models import Usuario
from app.orders.schemas import CustomerMenuOutput, OrderOutput, OrderPage, RestaurantOutput
from app.orders.service import customer_menu, customer_restaurants, list_orders, read_order

router = APIRouter(tags=["Pedidos"])
Customer = Annotated[Usuario, Depends(require_roles("cliente"))]
PositiveId = Annotated[int, Path(gt=0)]


@router.get("/restaurantes", response_model=list[RestaurantOutput])
def restaurants(db: DB, user: Customer):
    return customer_restaurants(db)


@router.get("/restaurantes/{id_restaurante}/menu", response_model=CustomerMenuOutput)
def menu(id_restaurante: PositiveId, db: DB, user: Customer):
    return customer_menu(db, id_restaurante)


@router.get("/pedidos", response_model=OrderPage)
def orders(db: DB, user: CurrentUser,
           limit: Annotated[int, Query(ge=1, le=100)] = 20,
           offset: Annotated[int, Query(ge=0)] = 0):
    return list_orders(db, user, limit, offset)


@router.get("/pedidos/{id_pedido}", response_model=OrderOutput)
def order(id_pedido: PositiveId, db: DB, user: CurrentUser):
    return read_order(db, user, id_pedido)
