from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.couriers.schemas import AvailabilityInput, CourierOutput, CourierPage
from app.db.models import HistorialRepartidor, Repartidor, Restaurante, Usuario
from app.orders.service import courier_available, lock_order_relations


def courier_query(restaurant_id: int):
    last_change = select(func.max(HistorialRepartidor.fecha_hora)).where(
        HistorialRepartidor.id_repartidor == Repartidor.id_repartidor).correlate(Repartidor).scalar_subquery()
    return (select(Repartidor.id_repartidor, Usuario.nombre, Repartidor.zona, Usuario.activo,
                   Repartidor.estado_disponibilidad, last_change.label("ultimo_cambio"))
            .join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
            .where(Usuario.id_restaurante == restaurant_id, Usuario.rol == "repartidor"))


def list_couriers(db: Session, user: Usuario) -> CourierPage:
    restaurant = db.execute(select(Restaurante.abierto, courier_available(Restaurante.id_restaurante))
                            .where(Restaurante.id_restaurante == user.id_restaurante)).first()
    if restaurant is None:
        raise HTTPException(404, "Restaurante no disponible.")
    query = courier_query(user.id_restaurante)
    if user.rol == "repartidor":
        query = query.where(Repartidor.id_usuario == user.id_usuario)
    rows = db.execute(query.order_by(Usuario.nombre, Repartidor.id_repartidor)).mappings()
    return CourierPage(id_restaurante=user.id_restaurante, abierto=restaurant[0],
                       delivery_disponible=restaurant[0] and restaurant[1],
                       repartidores=[CourierOutput(**row) for row in rows])


def update_availability(db: Session, user: Usuario, courier_id: int | None, data: AvailabilityInput) -> CourierOutput:
    lock_order_relations(db)
    query = select(Repartidor, Usuario).join(Usuario, Usuario.id_usuario == Repartidor.id_usuario).where(
        Usuario.id_restaurante == user.id_restaurante, Usuario.rol == "repartidor")
    if user.rol == "repartidor":
        query = query.where(Repartidor.id_usuario == user.id_usuario)
    else:
        query = query.where(Repartidor.id_repartidor == courier_id)
    row = db.execute(query.with_for_update()).first()
    if row is None:
        raise HTTPException(404, "Repartidor no disponible en este restaurante.")
    courier, account = row
    if not account.activo:
        raise HTTPException(409, "La cuenta del repartidor está inactiva.")
    try:
        if courier.estado_disponibilidad != data.estado_disponibilidad:
            courier.estado_disponibilidad = data.estado_disponibilidad
            db.add(HistorialRepartidor(id_repartidor=courier.id_repartidor, estado=courier.estado_disponibilidad))
            db.flush()
        result = CourierOutput(**db.execute(courier_query(user.id_restaurante)
                                             .where(Repartidor.id_repartidor == courier.id_repartidor)).mappings().one())
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo guardar la disponibilidad. Actualizá y volvé a intentar.") from None
