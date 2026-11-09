from typing import Annotated
import secrets

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, select

from app.auth.dependencies import DB, require_restaurant, require_roles
from app.db.models import Repartidor, Usuario
from app.support.service import DiagnosticInput, DiagnosticOutput, diagnose_account
from app.auth.models import CambioClavePendiente, Sesion
from app.auth.security import PASSWORD_HASHER, digest, verify_password
from app.auth.service import lock_email, login, valid_user

router = APIRouter(tags=["Soporte de cuentas"])
Admin = Annotated[Usuario, Depends(require_roles("administrador_plataforma"))]
Owner = Annotated[Usuario, Depends(require_restaurant("propietario"))]


@router.post("/admin/diagnostico-cuenta", response_model=DiagnosticOutput)
def account_diagnostic(data: DiagnosticInput, db: DB, user: Admin):
    # POST evita incluir el correo en URLs y registros de acceso. No escribe datos.
    return diagnose_account(db, data.correo)


class CompromiseInput(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    contrasena_administrador: SecretStr = Field(min_length=1, max_length=128)


def reset_compromised_account(id_usuario: int, data: CompromiseInput, db, user):
    target = db.scalar(select(Usuario).where(Usuario.id_usuario == id_usuario))
    def permitted(account):
        return (account is not None and valid_user(account) and account.id_usuario != user.id_usuario
                and (user.rol == 'administrador_plataforma' or
                     user.rol == 'propietario' and account.id_restaurante == user.id_restaurante
                     and account.rol in {'personal', 'repartidor'}))
    if not permitted(target):
        raise HTTPException(404, 'Cuenta no disponible para restablecimiento.')
    authenticated = login(db, user.correo, data.contrasena_administrador.get_secret_value())
    if authenticated is None:
        raise HTTPException(401, 'No se pudo verificar la identidad del administrador.')
    lock_email(db, digest(user.correo))
    actor = db.get(Usuario, user.id_usuario, with_for_update=True, populate_existing=True)
    if (not valid_user(actor) or actor.rol not in {'propietario', 'administrador_plataforma'}
            or not verify_password(actor.hash_contrasena, data.contrasena_administrador.get_secret_value())
            or db.get(Sesion, digest(authenticated[1])) is None):
        db.execute(delete(Sesion).where(Sesion.token_hash == digest(authenticated[1])))
        db.commit()
        raise HTTPException(401, 'No se pudo verificar la identidad del administrador.')
    db.execute(delete(Sesion).where(Sesion.token_hash == digest(authenticated[1])))
    lock_email(db, digest(target.correo))
    target = db.get(Usuario, id_usuario, with_for_update=True, populate_existing=True)
    if not permitted(target):
        db.commit()
        raise HTTPException(404, 'Cuenta no disponible para restablecimiento.')
    temporary = secrets.token_urlsafe(15)
    target.hash_contrasena = PASSWORD_HASHER.hash(temporary)
    if db.get(CambioClavePendiente, id_usuario) is None:
        db.add(CambioClavePendiente(id_usuario=id_usuario))
    db.execute(delete(Sesion).where(Sesion.id_usuario == id_usuario))
    db.commit()
    return {'contrasena_temporal': temporary}


@router.post('/admin/cuentas/{id_usuario}/compromiso')
def report_compromise(id_usuario: Annotated[int, Path(gt=0)], data: CompromiseInput, db: DB, user: Admin):
    return reset_compromised_account(id_usuario, data, db, user)


@router.post('/restaurantes/{id_restaurante}/personal/{id_usuario}/compromiso')
def report_staff_compromise(id_restaurante: Annotated[int, Path(gt=0)], id_usuario: Annotated[int, Path(gt=0)],
                            data: CompromiseInput, db: DB, user: Owner):
    target = db.scalar(select(Usuario.id_usuario).where(Usuario.id_usuario == id_usuario,
        Usuario.id_restaurante == id_restaurante, Usuario.rol == 'personal'))
    if target is None:
        raise HTTPException(404, 'Cuenta no disponible para restablecimiento.')
    return reset_compromised_account(id_usuario, data, db, user)


@router.post('/restaurantes/{id_restaurante}/repartidores/{id_repartidor}/compromiso')
def report_courier_compromise(id_restaurante: Annotated[int, Path(gt=0)], id_repartidor: Annotated[int, Path(gt=0)],
                              data: CompromiseInput, db: DB, user: Owner):
    target = db.scalar(select(Usuario.id_usuario).join(Repartidor, Repartidor.id_usuario == Usuario.id_usuario)
                       .where(Repartidor.id_repartidor == id_repartidor, Usuario.id_restaurante == id_restaurante,
                              Usuario.rol == 'repartidor'))
    if target is None:
        raise HTTPException(404, 'Cuenta no disponible para restablecimiento.')
    return reset_compromised_account(target, data, db, user)
