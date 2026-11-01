from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.couriers.schemas import AvailabilityInput, CourierOutput, CourierPage
from app.db.models import Entrega, HistorialRepartidor, Repartidor, Restaurante, Usuario
from app.orders.service import courier_available, lock_order_relations
from app.auth.security import digest, hash_password
from app.auth.service import lock_email
from app.couriers.schemas import CourierInput, RatesInput


def create_courier(db: Session, user: Usuario, data: CourierInput) -> CourierOutput:
    # No se vinculan ni se transfieren cuentas existentes entre restaurantes.
    try:
        encoded = hash_password(data.contrasena.get_secret_value())
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    lock_order_relations(db)
    lock_email(db, digest(data.correo))
    if db.scalar(select(Usuario.id_usuario).where(func.lower(Usuario.correo) == data.correo)):
        raise HTTPException(409, "No se puede crear una cuenta con ese correo.")
    account = Usuario(id_restaurante=user.id_restaurante, nombre=data.nombre, correo=data.correo,
                      hash_contrasena=encoded, telefono=data.telefono or None, rol="repartidor", activo=True)
    try:
        db.add(account)
        db.flush()
        courier = Repartidor(id_usuario=account.id_usuario, zona=data.zona or None,
                             estado_disponibilidad="No disponible")
        db.add(courier)
        db.flush()
        db.add(HistorialRepartidor(id_repartidor=courier.id_repartidor, estado="No disponible"))
        db.flush()
        result = CourierOutput(**db.execute(courier_query(user.id_restaurante)
                    .where(Repartidor.id_repartidor == courier.id_repartidor)).mappings().one())
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo crear la cuenta del repartidor.") from None


def restaurant_rates(db: Session, restaurant_id: int, data: RatesInput | None = None):
    if data is not None:
        lock_order_relations(db)
    query = select(Restaurante).where(Restaurante.id_restaurante == restaurant_id)
    row = db.scalar(query.with_for_update() if data is not None else query)
    if row is None:
        raise HTTPException(404, "Restaurante no disponible.")
    if data is not None:
        row.costo_fijo_entrega = data.costo_fijo_entrega
        row.costo_por_km = data.costo_por_km
        db.commit()
    return row


def courier_query(restaurant_id: int):
    last_change = select(func.max(HistorialRepartidor.fecha_hora)).where(
        HistorialRepartidor.id_repartidor == Repartidor.id_repartidor).correlate(Repartidor).scalar_subquery()
    active = select(Entrega.id_entrega).where(Entrega.id_repartidor == Repartidor.id_repartidor,
        Entrega.estado.in_(['Asignado', 'En camino', 'asignada'])).exists()
    return (select(Repartidor.id_repartidor, Usuario.nombre, Repartidor.zona, Usuario.activo,
                   Repartidor.estado_disponibilidad, last_change.label("ultimo_cambio"), active.label('entrega_activa'))
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
    if data.estado_disponibilidad == 'Disponible' and db.scalar(select(Entrega.id_entrega).where(
            Entrega.id_repartidor == courier.id_repartidor, Entrega.estado.in_(['Asignado', 'En camino', 'asignada'])).limit(1)):
        raise HTTPException(409, 'El repartidor tiene una entrega activa. Finalizala antes de marcarlo disponible.')
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
