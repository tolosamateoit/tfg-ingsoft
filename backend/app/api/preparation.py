from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.auth.dependencies import DB, require_restaurant
from app.db.models import Usuario
from app.preparation.schemas import PreparationInput, PreparationOutput, StockOutput
from app.preparation.service import change_preparation, preparation, stock

router = APIRouter(prefix="/restaurantes/{id_restaurante}", tags=["Preparación y stock"])
Staff = Annotated[Usuario, Depends(require_restaurant("personal", "propietario"))]
PositiveId = Annotated[int, Path(gt=0)]


@router.get("/stock", response_model=list[StockOutput])
def inventory(id_restaurante: PositiveId, db: DB, user: Staff):
    return stock(db, id_restaurante)


@router.get("/pedidos/{id_pedido}/preparacion", response_model=PreparationOutput)
def read_preparation(id_restaurante: PositiveId, id_pedido: PositiveId, db: DB, user: Staff):
    return preparation(db, id_restaurante, id_pedido)


@router.put("/pedidos/{id_pedido}/preparacion", response_model=PreparationOutput)
def update_preparation(id_restaurante: PositiveId, id_pedido: PositiveId, data: PreparationInput, db: DB, user: Staff):
    return change_preparation(db, user, id_restaurante, id_pedido, data)
