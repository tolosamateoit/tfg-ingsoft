"""Simulación local de pedidos marcados al crearse, sin fechas históricas como reloj.

Un solo worker posee el lock de sesión. Al reiniciar comienza un nuevo intervalo
de etapa: nunca se acumula tiempo con el servidor apagado. Sin pedidos pendientes
solo se descubre trabajo cada 30 segundos; el resto del reloj vive en memoria.
"""
import logging
from threading import Event, Thread
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

from app.auth.config import get_auth_settings
from app.auth.database import get_engine
from app.db.models import Pedido, HistorialPedido, Usuario, Entrega

MARKER = 'demo_simulacion'
ACTIVE = ('Nuevo', 'En preparación', 'Listo', 'Asignado', 'En camino')
log = logging.getLogger(__name__)


def local_demo():
    try:
        return not get_auth_settings().cookie_secure
    except ValueError:
        return False


def delay(order_id, state):
    return 15 + (order_id + len(state)) % 11


def advance(db, order_id, *, expected_state=None, ready_ids=None):
    from app.orders.service import lock_order_relations
    from app.preparation.service import change_preparation
    from app.preparation.schemas import PreparationInput
    from app.logistics.service import assign_ready_orders, change_delivery_state
    from app.logistics.schemas import DeliveryStateInput
    lock_order_relations(db)
    order = db.get(Pedido, order_id, with_for_update=True)
    if order is None or order.estado not in ACTIVE:
        return None
    if expected_state is not None and order.estado != expected_state:
        return order.estado
    actor = db.scalar(select(Usuario).where(Usuario.id_restaurante == order.id_restaurante,
        Usuario.rol == 'propietario', Usuario.activo.is_(True)).order_by(Usuario.id_usuario).limit(1))
    if actor is None:
        return order.estado
    if order.estado in ('Nuevo', 'En preparación'):
        version = db.scalar(select(func.max(HistorialPedido.id_historial)).where(HistorialPedido.id_pedido == order_id)) or 0
        change_preparation(db, actor, order.id_restaurante, order_id, PreparationInput(
            estado='En preparación' if order.estado == 'Nuevo' else 'Listo', version=version))
    elif order.estado == 'Listo':
        # El lote automático solo incluye pedidos nuevos marcados para esta demo.
        assign_ready_orders(db, actor, order.id_restaurante, demo_only=True,
                            eligible_order_ids=ready_ids if ready_ids is not None else [order_id])
    else:
        delivery = db.scalar(select(Entrega).where(Entrega.id_pedido == order_id))
        if delivery:
            change_delivery_state(db, actor, delivery.id_entrega, DeliveryStateInput(
                estado='En camino' if order.estado == 'Asignado' else 'Entregado'))
    return order.estado


def run_once(stop):
    pending = {}
    discovery = 0
    try:
        with get_engine().connect() as connection:
            if not connection.scalar(text('SELECT pg_try_advisory_lock(1647042, 26)')):
                return
            connection.commit()
            try:
                while not stop.is_set():
                    now = monotonic()
                    if now >= discovery:
                        with Session(connection) as db:
                            rows = db.execute(select(Pedido.id_pedido, Pedido.estado).where(Pedido.estado.in_(ACTIVE),
                                select(HistorialPedido.id_historial).where(HistorialPedido.id_pedido == Pedido.id_pedido,
                                    HistorialPedido.tipo_evento == 'registro',
                                    HistorialPedido.detalle.endswith(f'[{MARKER}]')).exists())).all()
                        for oid, state in rows:
                            if oid not in pending or pending[oid][0] != state:
                                pending[oid] = (state, now + delay(oid, state))
                        discovery = now + 30
                    for oid, (expected, due) in list(pending.items()):
                        if now < due:
                            continue
                        ready_ids = [key for key, (state, deadline) in pending.items()
                                     if state == 'Listo' and deadline <= now]
                        try:
                            with Session(connection, expire_on_commit=False) as db:
                                state = advance(db, oid, expected_state=expected, ready_ids=ready_ids)
                            if state in ACTIVE:
                                pending[oid] = (state, monotonic() + delay(oid, state))
                            else:
                                pending.pop(oid, None)
                        except HTTPException:
                            pending[oid] = (expected, monotonic() + 30)
                    stop.wait(1)
            finally:
                connection.rollback()
                connection.execute(text('SELECT pg_advisory_unlock(1647042, 26)'))
                connection.commit()
    except Exception:
        # No imprimir parámetros ni credenciales de conexión.
        log.error('La simulación local no pudo continuar; se reintentará.')


def run(stop):
    while not stop.is_set():
        run_once(stop)
        stop.wait(30)


def start():
    stop = Event()
    thread = Thread(target=run, args=(stop,), daemon=True, name='demo-orders')
    thread.start()
    return stop, thread
