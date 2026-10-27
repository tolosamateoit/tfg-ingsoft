from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.auth.models import EstadoAcceso
from app.auth.security import digest, normalize_email
from app.auth.service import RESTAURANT_ROLES, ROLES, as_utc, utc_now, valid_user
from app.db.models import Cliente, Repartidor, Usuario


class DiagnosticInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: str = Field(max_length=254)

    @field_validator("correo")
    @classmethod
    def normalized(cls, value: str) -> str:
        return normalize_email(value)


class DiagnosticOutput(BaseModel):
    id_usuario: int
    correo: str
    rol: str
    activo: bool
    id_restaurante: int | None
    rol_reconocido: bool
    pertenencia_configurada: bool
    perfil_operativo_completo: bool
    bloqueo_temporal: bool
    bloqueado_hasta: datetime | None
    acceso_habilitado: bool


def diagnose_account(db: Session, email: str) -> DiagnosticOutput:
    # No cargar contraseñas, teléfonos, direcciones, sesiones ni recursos operativos.
    target = db.scalar(select(Usuario).options(load_only(Usuario.id_usuario, Usuario.correo, Usuario.rol,
                                                        Usuario.activo, Usuario.id_restaurante))
                       .where(Usuario.correo == email))
    if target is None:
        raise HTTPException(404, "No se encontró una cuenta con ese correo exacto.")
    profile = True
    if target.rol == "cliente":
        profile = db.scalar(select(Cliente.id_cliente).where(Cliente.id_usuario == target.id_usuario)) is not None
    elif target.rol == "repartidor":
        profile = db.scalar(select(Repartidor.id_repartidor).where(Repartidor.id_usuario == target.id_usuario)) is not None
    state = db.get(EstadoAcceso, digest(email))
    blocked = bool(state and state.bloqueado_hasta and as_utc(state.bloqueado_hasta) > utc_now())
    return DiagnosticOutput(id_usuario=target.id_usuario, correo=target.correo, rol=target.rol, activo=target.activo,
                            id_restaurante=target.id_restaurante, rol_reconocido=target.rol in ROLES,
                            pertenencia_configurada=target.rol not in RESTAURANT_ROLES or target.id_restaurante is not None,
                            perfil_operativo_completo=profile, bloqueo_temporal=blocked,
                            bloqueado_hasta=as_utc(state.bloqueado_hasta) if blocked else None,
                            acceso_habilitado=valid_user(target) and not blocked)
