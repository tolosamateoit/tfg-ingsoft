from fractions import Fraction
from decimal import Decimal, ROUND_HALF_UP, localcontext

from fastapi import HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Cliente, Entrega, HistorialPedido, HistorialRepartidor, Pedido, Repartidor, Restaurante, Usuario
from app.logistics.priority import PENDING, calculate
from app.logistics.schemas import AssignmentInput, AssignmentOutput, DeliveryOutput, DeliveryStateInput, DistanceInput, TrackingEvent, TrackingOutput
from app.orders.service import lock_order_relations, state_since_query
from app.orders.summaries import summary_data
from app.preparation.service import scoped_order
from app.orders.distance import unconfirmed_distances

IN_PROGRESS = ("Asignado", "En camino", "asignada")
FINISHED = ("Entregado", "No entregado")


def delivery_cost(restaurant: Restaurante, order: Pedido) -> Decimal:
    with localcontext() as context:
        context.prec = 40
        cost = (restaurant.costo_fijo_entrega + restaurant.costo_por_km * order.distancia_km).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    if cost > Decimal("9999999999999999.99"):
        raise HTTPException(422, "El costo de entrega supera el máximo permitido.")
    return cost


def assign_ready_orders(db: Session, user: Usuario, restaurant_id: int, selection: AssignmentInput | None = None) -> AssignmentOutput:
    lock_order_relations(db)
    restaurant = db.scalar(select(Restaurante).where(Restaurante.id_restaurante == restaurant_id).with_for_update(read=True))
    if restaurant is None:
        raise HTTPException(404, "Restaurante no disponible.")
    # Bloquear primero en orden estable; luego ordenar por el puntaje vigente.
    ready_query = select(Pedido).where(Pedido.id_restaurante == restaurant_id, Pedido.estado == 'Listo',
        ~exists(select(Entrega.id_entrega).where(Entrega.id_pedido == Pedido.id_pedido)))
    if selection is not None:
        ready_query = ready_query.where(Pedido.id_pedido == selection.id_pedido)
    ready = db.scalars(ready_query
        .order_by(func.coalesce(state_since_query(), Pedido.fecha_hora), Pedido.fecha_hora, Pedido.id_pedido)
        .with_for_update()).all()
    unknown = unconfirmed_distances(db, [o.id_pedido for o in ready])
    now = db.scalar(select(func.now()))
    for order in ready:
        calculate(order, now, distance_known=order.id_pedido not in unknown)
    ready.sort(key=lambda order: (-order.puntaje_prioridad, order.fecha_hora, order.id_pedido))
    eligible = [order for order in ready if order.id_pedido not in unknown and order.distancia_km <= 10]
    candidates = ranked_couriers(db, restaurant_id, courier_id=selection.id_repartidor if selection else None,
                                 user=user if selection is None else None)
    if selection is not None:
        if not ready:
            scoped_order(db, restaurant_id, selection.id_pedido, lock=True)
            raise HTTPException(409, 'El pedido ya no está listo para asignar.')
        order = ready[0]
        version = db.scalar(select(func.max(HistorialPedido.id_historial)).where(HistorialPedido.id_pedido == order.id_pedido)) or 0
        if version != selection.version:
            raise HTTPException(409, 'El pedido cambió. Actualizá los pedidos antes de asignarlo.')
        candidates = [row for row in candidates if row[0].id_repartidor == selection.id_repartidor]
        if not candidates:
            raise HTTPException(409, 'El repartidor no está disponible en este restaurante.')
        if selection.distancia_km is not None:
            if order.distancia_km != selection.distancia_km or order.id_pedido in unknown:
                db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=user.id_usuario, tipo_evento='distancia',
                    estado='Listo', detalle=f'Distancia registrada: {selection.distancia_km} km.'))
                order.distancia_km = selection.distancia_km
        elif order.id_pedido in unknown:
            raise HTTPException(409, 'Falta una distancia válida para calcular el envío. Ingresala al asignar.')
        if order.distancia_km > 10:
            raise HTTPException(422, 'La distancia de entrega supera la cobertura de 10 km.')
        ready, eligible = [order], [order]
    # Cada candidato se usa una sola vez en este lote.
    plan = [(order, courier, account, delivery_cost(restaurant, order))
            for order, (courier, account) in zip(eligible, candidates)]
    created = []
    try:
        for order, courier, account, cost in plan:
            delivery = Entrega(id_pedido=order.id_pedido, id_repartidor=courier.id_repartidor,
                               estado="Asignado", costo_repartidor=cost)
            db.add(delivery)
            order.estado = "Asignado"
            courier.estado_disponibilidad = "No disponible"
            db.add(HistorialRepartidor(id_repartidor=courier.id_repartidor, estado="No disponible"))
            db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=user.id_usuario, tipo_evento="asignacion",
                                  estado="Asignado", detalle=f"Repartidor asignado: {account.nombre} (#{courier.id_repartidor})."
                                  + (' Elegido por disponibilidad y entregas exitosas; empates por nombre.' if selection is None else ' Selección manual.')))
            created.append(delivery)
        db.flush()
        ids = [delivery.id_entrega for delivery in created]
        by_id = {row[0].id_entrega: delivery_output(row) for row in db.execute(
            delivery_query(user).where(Entrega.id_entrega.in_(ids))).all()}
        result = AssignmentOutput(entregas=[by_id[id] for id in ids], pendientes=len(ready) - len(created))
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo guardar la asignación. Actualizá y volvé a intentar.") from None


def delivery_query(user: Usuario):
    query = (select(Entrega, Pedido, Usuario.nombre, Cliente.nombre)
             .join(Pedido, Pedido.id_pedido == Entrega.id_pedido)
             .join(Cliente, Cliente.id_cliente == Pedido.id_cliente)
             .join(Repartidor, Repartidor.id_repartidor == Entrega.id_repartidor)
             .join(Usuario, Usuario.id_usuario == Repartidor.id_usuario))
    if user.rol in {"personal", "propietario"}:
        return query.where(Pedido.id_restaurante == user.id_restaurante, Usuario.id_restaurante == user.id_restaurante)
    if user.rol == "repartidor":
        return query.where(Repartidor.id_usuario == user.id_usuario, Pedido.id_restaurante == user.id_restaurante)
    if user.rol == "cliente":
        return query.where(Cliente.id_usuario == user.id_usuario)
    raise HTTPException(403, "No tenés permiso para consultar entregas.")


def delivery_output(row) -> DeliveryOutput:
    delivery, order, courier, client = row
    return DeliveryOutput(id_entrega=delivery.id_entrega, id_pedido=order.id_pedido,
                          id_repartidor=delivery.id_repartidor, repartidor=courier, cliente=client,
                          direccion_entrega=order.direccion_entrega, referencia_local=order.referencia_local,
                          estado=delivery.estado, fecha_asignacion=delivery.fecha_asignacion,
                          distancia_km=order.distancia_km)


def deliveries(db: Session, user: Usuario, offset: int, *, warnings=None, active_only=False) -> list[DeliveryOutput]:
    query = delivery_query(user)
    if active_only:
        query = query.where(Entrega.estado.in_(IN_PROGRESS))
    rows = db.execute(query
            .order_by(Pedido.fecha_hora.desc(), Pedido.id_pedido.desc()).offset(offset).limit(20)).all()
    extra = summary_data(db, [row[1].id_pedido for row in rows])
    from app.analytics.operational import owner_order_warnings
    if warnings is None:
        warnings = owner_order_warnings(db, user, [row[1].id_pedido for row in rows], target_orders=[row[1] for row in rows])
    return [delivery_output(row).model_copy(update={"resumen_productos": extra[row[1].id_pedido]["resumen_productos"],
            'advertencia_entrega': warnings.get(row[1].id_pedido, {}).get('advertencia_entrega')}) for row in rows]


def tracking(db: Session, user: Usuario, order_id: int) -> TrackingOutput:
    query = select(Pedido).join(Cliente, Cliente.id_cliente == Pedido.id_cliente).where(Pedido.id_pedido == order_id)
    if user.rol in {"personal", "propietario"}:
        query = query.where(Pedido.id_restaurante == user.id_restaurante)
    elif user.rol == "cliente":
        query = query.where(Cliente.id_usuario == user.id_usuario)
    elif user.rol == "repartidor":
        query = query.join(Entrega, Entrega.id_pedido == Pedido.id_pedido).join(Repartidor).where(
            Repartidor.id_usuario == user.id_usuario, Pedido.id_restaurante == user.id_restaurante)
    else:
        raise HTTPException(403, "No tenés permiso para consultar el seguimiento.")
    order = db.scalar(query)
    if order is None:
        raise HTTPException(404, "Pedido no disponible.")
    return _tracking_output(db, user, order)


def _tracking_output(db, user, order, row=None):
    """Respuesta para un pedido ya autorizado dentro de la misma transacción."""
    order_id = order.id_pedido
    if row is None:
        row = db.execute(delivery_query(user).where(Entrega.id_pedido == order_id)).first()
    events = db.execute(select(HistorialPedido.id_historial, HistorialPedido.fecha_hora,
                               Usuario.nombre.label("usuario"), HistorialPedido.estado, HistorialPedido.detalle)
                        .join(Usuario, Usuario.id_usuario == HistorialPedido.id_usuario)
                        .where(HistorialPedido.id_pedido == order_id)
                        .order_by(HistorialPedido.fecha_hora, HistorialPedido.id_historial)).mappings()
    delivery = delivery_output(row) if row else None
    if delivery and user.rol == 'propietario':
        from app.analytics.operational import owner_order_warnings
        delivery.advertencia_entrega = owner_order_warnings(db, user, [order_id], target_orders=[order]).get(order_id, {}).get('advertencia_entrega')
    return TrackingOutput(id_pedido=order_id, estado_pedido=order.estado,
                          entrega=delivery,
                          historial=[TrackingEvent(**{**event, 'usuario': None, 'detalle': None} if user.rol == 'cliente' else event) for event in events])


def change_distance(db: Session, user: Usuario, restaurant_id: int, order_id: int, data: DistanceInput) -> TrackingOutput:
    lock_order_relations(db)
    order = scoped_order(db, restaurant_id, order_id, lock=True)
    if order.estado not in {"Nuevo", "En preparación", "Listo"} or db.scalar(select(Entrega.id_entrega).where(Entrega.id_pedido == order_id)):
        raise HTTPException(409, "La distancia solo puede corregirse antes de asignar la entrega.")
    if order.distancia_km != data.distancia_km or order_id in unconfirmed_distances(db, [order_id]):
        previous = order.distancia_km
        order.distancia_km = data.distancia_km
        if order.estado in PENDING:
            calculate(order, db.scalar(select(func.now())))
        db.add(HistorialPedido(id_pedido=order_id, id_usuario=user.id_usuario, tipo_evento="distancia", estado=order.estado,
                              detalle=f"Distancia estimada: {previous} → {data.distancia_km} km."))
    db.flush()
    result = _tracking_output(db, user, order)
    db.commit()
    return result


def ranked_couriers(db: Session, restaurant_id: int, *, courier_id=None, user=None):
    query = select(Repartidor, Usuario).join(Usuario, Usuario.id_usuario == Repartidor.id_usuario)
    if courier_id is not None:
        query = query.where(Repartidor.id_repartidor == courier_id)
    candidates = db.execute(query
                            .where(Usuario.id_restaurante == restaurant_id, Usuario.rol == "repartidor", Usuario.activo.is_(True),
                                   Repartidor.estado_disponibilidad == "Disponible",
                                   ~exists(select(Entrega.id_entrega).where(Entrega.id_repartidor == Repartidor.id_repartidor,
                                                                          Entrega.estado.in_(IN_PROGRESS))))
                            .order_by(Repartidor.id_repartidor).with_for_update()).all()
    if courier_id is not None:
        return candidates
    if user is not None:
        from app.couriers.performance import performance
        averages = {courier.id_repartidor: performance(db, user, courier.id_repartidor)['promedio_minutos']
                    for courier, _ in candidates}
        return sorted(candidates, key=lambda row: (
            averages[row[0].id_repartidor] is None,
            averages[row[0].id_repartidor] if averages[row[0].id_repartidor] is not None else 0,
            row[1].nombre.casefold(), row[1].nombre, row[0].id_repartidor))
    stats = {courier.id_repartidor: [0, 0, 0] for courier, _ in candidates}
    rows = db.execute(select(Entrega.id_repartidor, Entrega.estado, func.count())
                      .join(Pedido, Pedido.id_pedido == Entrega.id_pedido)
                      .where(Pedido.id_restaurante == restaurant_id, Entrega.id_repartidor.in_(stats))
                      .group_by(Entrega.id_repartidor, Entrega.estado)).all()
    for courier_id, state, count in rows:
        if state in IN_PROGRESS:
            stats[courier_id][0] += count
        if state in FINISHED:
            stats[courier_id][2] += count
            if state == "Entregado":
                stats[courier_id][1] += count
    return sorted(candidates, key=lambda row: (stats[row[0].id_repartidor][0],
                  -Fraction(stats[row[0].id_repartidor][1], stats[row[0].id_repartidor][2] or 1),
                  row[1].nombre.casefold(), row[1].nombre, row[0].id_repartidor))


def change_delivery_state(db: Session, user: Usuario, delivery_id: int, data: DeliveryStateInput) -> TrackingOutput:
    if user.rol != "repartidor":
        raise HTTPException(403, "Solo el repartidor asignado puede actualizar la entrega.")
    lock_order_relations(db)
    row = db.execute(delivery_query(user).where(Entrega.id_entrega == delivery_id).with_for_update()).first()
    if row is None:
        raise HTTPException(404, "Entrega no disponible.")
    delivery, order, _, _ = row
    if data.estado == delivery.estado:
        return _tracking_output(db, user, order, row)
    if not (delivery.estado == "Asignado" and data.estado == "En camino"
            or delivery.estado == "En camino" and data.estado in FINISHED):
        raise HTTPException(409, "Transición de entrega no permitida.")
    try:
        delivery.estado = data.estado
        order.estado = data.estado
        if data.estado == 'Entregado' and order.estado_pago != 'pagado':
            order.estado_pago = 'pagado'
        db.add(HistorialPedido(id_pedido=order.id_pedido, id_usuario=user.id_usuario, tipo_evento="entrega",
                              estado=data.estado, detalle=f"Entrega #{delivery_id}: {data.estado}."
                              + (' Pago confirmado.' if data.estado == 'Entregado' else '')))
        db.flush()
        db.flush()
        result = _tracking_output(db, user, order, row)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "No se pudo actualizar la entrega. Actualizá y volvé a intentar.") from None
