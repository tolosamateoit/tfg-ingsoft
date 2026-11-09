"""Login transaccional; contadores persistidos también para correos inexistentes."""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.auth.models import EstadoAcceso, Sesion
from app.auth.security import PASSWORD_HASHER, digest, verify_password
from app.db.models import Usuario

SESSION_TTL = timedelta(hours=8)
LOCK_TIME = timedelta(minutes=15)
ROLES = frozenset({"cliente", "personal", "propietario", "repartidor", "administrador_plataforma"})
RESTAURANT_ROLES = frozenset({"personal", "propietario", "repartidor"})


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def lock_email(db: Session, email_key: str):
    # Lock por correo ANTES de leer/crear el contador: funciona incluso si no existe fila.
    # Dos enteros reservan un espacio separado del lock de relaciones de etapa 2.
    lock_key = int.from_bytes(bytes.fromhex(email_key)[:4], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(1647043, :key)"), {"key": lock_key})


def valid_user(user: Usuario | None) -> bool:
    return bool(user and user.activo and user.rol in ROLES
                and (user.rol not in RESTAURANT_ROLES or user.id_restaurante is not None))


def login(db: Session, email: str, password: str) -> tuple[Usuario, str] | None:
    """Confirma también los fallos antes de devolver un error a la API."""
    key = digest(email)
    lock_email(db, key)
    # Tomar el reloj después de obtener el lock, no antes de una posible espera.
    now = utc_now()
    state = db.get(EstadoAcceso, key)
    if state is None:
        state = EstadoAcceso(clave_correo=key, intentos_fallidos=0, actualizado_en=now)
        db.add(state)
    blocked = state.bloqueado_hasta is not None and as_utc(state.bloqueado_hasta) > now
    if state.bloqueado_hasta is not None and not blocked:
        state.intentos_fallidos = 0
        state.bloqueado_hasta = None
    # Las cuentas de la demo se precargan con correo normalizado: usa UNIQUE(correo).
    user = db.scalar(select(Usuario).where(Usuario.correo == email))
    verified = verify_password(user.hash_contrasena if user else None, password)
    if blocked:
        db.commit()
        return None
    state.actualizado_en = now
    if not verified or not valid_user(user):
        state.intentos_fallidos += 1
        if state.intentos_fallidos == 5:
            state.bloqueado_hasta = now + LOCK_TIME
            if user is not None:
                db.execute(delete(Sesion).where(Sesion.id_usuario == user.id_usuario))
        db.commit()
        return None
    state.intentos_fallidos = 0
    state.bloqueado_hasta = None
    if PASSWORD_HASHER.check_needs_rehash(user.hash_contrasena):
        user.hash_contrasena = PASSWORD_HASHER.hash(password)
    token = secrets.token_urlsafe(32)
    db.add(Sesion(token_hash=digest(token), id_usuario=user.id_usuario,
                  creada_en=now, expira_en=now + SESSION_TTL))
    db.commit()
    return user, token
