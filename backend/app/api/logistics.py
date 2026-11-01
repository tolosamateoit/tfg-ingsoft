from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.auth.dependencies import CurrentUser, DB, require_restaurant, require_roles
from app.db.models import Usuario
from app.logistics.priority import priorities, priority_preview
from app.logistics.schemas import AssignmentInput, AssignmentOutput, DeliveryOutput, DeliveryStateInput, DistanceInput, PriorityPage, TrackingOutput
from app.logistics.service import assign_ready_orders, change_delivery_state, change_distance, deliveries, tracking

router = APIRouter(tags=["Prioridad y entregas"])
Staff = Annotated[Usuario, Depends(require_restaurant("personal", "propietario"))]
Courier = Annotated[Usuario, Depends(require_roles("repartidor"))]
DeliveryReader = Annotated[Usuario, Depends(require_roles("personal", "propietario", "repartidor"))]
PositiveId = Annotated[int, Path(gt=0)]


@router.post("/restaurantes/{id_restaurante}/entregas/asignar", response_model=AssignmentOutput)
def assign_deliveries(id_restaurante: PositiveId, db: DB, user: Staff, selection: AssignmentInput | None = None):
    return assign_ready_orders(db, user, id_restaurante, selection)


@router.get('/restaurantes/{id_restaurante}/prioridades', response_model=PriorityPage)
def live_priorities(id_restaurante: PositiveId, db: DB, user: Staff):
    return priority_warnings(db, user, priority_preview(db, id_restaurante))


def priority_warnings(db, user, result):
    from app.analytics.operational import owner_order_warnings
    warnings = owner_order_warnings(db, user, [row.id_pedido for row in result.pedidos])
    for row in result.pedidos:
        row.advertencia_importe = warnings.get(row.id_pedido, {}).get('advertencia_importe')
    return result


@router.post("/restaurantes/{id_restaurante}/prioridades", response_model=PriorityPage)
def recalculate(id_restaurante: PositiveId, db: DB, user: Staff):
    return priority_warnings(db, user, priorities(db, id_restaurante))


@router.put("/restaurantes/{id_restaurante}/pedidos/{id_pedido}/distancia", response_model=TrackingOutput)
def adjust_distance(id_restaurante: PositiveId, id_pedido: PositiveId, data: DistanceInput, db: DB, user: Staff):
    return change_distance(db, user, id_restaurante, id_pedido, data)


@router.get("/pedidos/{id_pedido}/seguimiento", response_model=TrackingOutput)
def follow_order(id_pedido: PositiveId, db: DB, user: CurrentUser):
    return tracking(db, user, id_pedido)


@router.get("/entregas", response_model=list[DeliveryOutput])
def list_deliveries(db: DB, user: DeliveryReader, offset: Annotated[int, Query(ge=0)] = 0):
    return deliveries(db, user, offset)


@router.put("/entregas/{id_entrega}/estado", response_model=TrackingOutput)
def update_delivery(id_entrega: PositiveId, data: DeliveryStateInput, db: DB, user: DeliveryReader):
    return change_delivery_state(db, user, id_entrega, data)
