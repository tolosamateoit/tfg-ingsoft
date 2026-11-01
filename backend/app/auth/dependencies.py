"""Denegar por defecto; consultar estado y pertenencia vigentes en cada petición."""

import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.config import AuthSettings, get_auth_settings
from app.auth.database import get_db
from app.auth.models import Sesion
from app.auth.security import digest
from app.auth.service import as_utc, utc_now, valid_user
from app.db.models import Cliente, Entrega, Pedido, Repartidor, Usuario

COOKIE_NAME = "tfg_session"
TAB_HEADER = "X-Oliva-Tab"
DB = Annotated[Session, Depends(get_db)]


def session_cookie_name(request: Request) -> str:
    tab = request.headers.get(TAB_HEADER)
    if tab is None:
        return COOKIE_NAME  # Compatibilidad con los clientes existentes de la API.
    if not re.fullmatch(r"[a-f0-9]{32}", tab):
        raise HTTPException(401, "Necesitás iniciar sesión.")
    return f"{COOKIE_NAME}_{tab}"


def auth_settings() -> AuthSettings:
    try:
        return get_auth_settings()
    except ValueError:
        raise HTTPException(503, "Autenticación temporalmente no disponible.") from None


def protect_mutation(request: Request, settings: Annotated[AuthSettings, Depends(auth_settings)]):
    # Encabezado no simple + origen exacto. No hay CORS con credenciales públicas.
    if (request.headers.get("origin") not in settings.allowed_origins
            or request.headers.get("x-csrf-protection") != "1"):
        raise HTTPException(403, "Origen de solicitud no permitido.")


@dataclass(frozen=True)
class Identity:
    user: Usuario
    session: Sesion


def current_identity(request: Request, db: DB,
                     settings: Annotated[AuthSettings, Depends(auth_settings)]) -> Identity:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        protect_mutation(request, settings)
    token = request.cookies.get(session_cookie_name(request), "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(401, "Necesitás iniciar sesión.")
    row = db.execute(
        select(Sesion, Usuario).join(Usuario, Usuario.id_usuario == Sesion.id_usuario)
        .where(Sesion.token_hash == digest(token))
    ).first()
    if not row or as_utc(row[0].expira_en) <= utc_now() or not valid_user(row[1]):
        raise HTTPException(401, "Necesitás iniciar sesión.")
    return Identity(row[1], row[0])


def current_user(identity: Annotated[Identity, Depends(current_identity)]) -> Usuario:
    return identity.user


CurrentUser = Annotated[Usuario, Depends(current_user)]


def require_roles(*roles: str):
    def dependency(user: CurrentUser):
        if user.rol not in roles:
            raise HTTPException(403, "No tenés permiso para esta operación.")
        return user
    return dependency


def restaurant_access(id_restaurante: int, user: Usuario, roles: frozenset[str]):
    # El administrador global no obtiene un bypass implícito.
    if (user.rol not in roles or user.id_restaurante is None
            or id_restaurante != user.id_restaurante):
        raise HTTPException(403, "No tenés permiso para esta operación.")


def require_restaurant(*roles: str):
    def dependency(id_restaurante: int, user: CurrentUser):
        restaurant_access(id_restaurante, user, frozenset(roles))
        return user
    return dependency


def own_client(id_cliente: int, db: DB, user: CurrentUser) -> Cliente:
    client = db.scalar(select(Cliente).where(
        Cliente.id_cliente == id_cliente, Cliente.id_usuario == user.id_usuario,
    ))
    if user.rol != "cliente" or client is None:
        raise HTTPException(404, "Recurso no disponible.")
    return client


def accessible_order(id_pedido: int, db: DB, user: CurrentUser) -> Pedido:
    query = select(Pedido).where(Pedido.id_pedido == id_pedido)
    if user.rol in {"personal", "propietario"} and user.id_restaurante is not None:
        query = query.where(Pedido.id_restaurante == user.id_restaurante)
    elif user.rol == "cliente":
        query = query.join(Cliente).where(Cliente.id_usuario == user.id_usuario)
    else:
        raise HTTPException(403, "No tenés permiso para esta operación.")
    order = db.scalar(query)
    if order is None:
        raise HTTPException(404, "Recurso no disponible.")
    return order


def assigned_delivery(id_entrega: int, db: DB, user: CurrentUser) -> Entrega:
    if user.rol != "repartidor" or user.id_restaurante is None:
        raise HTTPException(403, "No tenés permiso para esta operación.")
    delivery = db.scalar(
        select(Entrega).join(Repartidor).join(Pedido)
        .where(Entrega.id_entrega == id_entrega,
               Repartidor.id_usuario == user.id_usuario,
               Pedido.id_restaurante == user.id_restaurante)
    )
    if delivery is None:
        raise HTTPException(404, "Recurso no disponible.")
    return delivery
