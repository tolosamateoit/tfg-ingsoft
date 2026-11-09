"""Únicos endpoints funcionales de esta etapa: login, sesión y logout."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import delete

from app.auth.config import AuthSettings
from app.auth.dependencies import (
    DB, CurrentUser, Identity, auth_settings, current_identity, protect_mutation, session_cookie_name,
)
from app.auth.models import CambioClavePendiente, Sesion
from app.auth.security import hash_password, normalize_email, verify_password
from app.auth.service import SESSION_TTL, lock_email, login
from app.auth.security import digest
from app.db.models import Usuario

router = APIRouter(prefix="/auth", tags=["Autenticación"])
LOGIN_ERROR = "No se pudo iniciar sesión. Verificá los datos o intentá nuevamente en 15 minutos."


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    correo: str = Field(min_length=3, max_length=254)
    contrasena: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("correo")
    @classmethod
    def email(cls, value):
        return normalize_email(value)


class UserOutput(BaseModel):
    id_usuario: int
    nombre: str
    correo: str
    rol: str
    id_restaurante: int | None
    restaurante: str | None = None
    cambio_contrasena_obligatorio: bool = False


def public_user(user, db) -> UserOutput:
    values = {name: getattr(user, name) for name in UserOutput.model_fields if name not in {'restaurante', 'cambio_contrasena_obligatorio'}}
    restaurant = getattr(user, 'restaurante', None)
    return UserOutput(**values, restaurante=restaurant.nombre if restaurant else None,
                      cambio_contrasena_obligatorio=db.get(CambioClavePendiente, user.id_usuario) is not None)


@router.post("/login", response_model=UserOutput, dependencies=[Depends(protect_mutation)])
def sign_in(data: LoginInput, request: Request, response: Response, db: DB,
            settings: Annotated[AuthSettings, Depends(auth_settings)]):
    cookie_name = session_cookie_name(request)
    result = login(db, data.correo, data.contrasena.get_secret_value())
    if result is None:
        raise HTTPException(401, LOGIN_ERROR)
    user, token = result
    response.set_cookie(cookie_name, token, max_age=int(SESSION_TTL.total_seconds()),
                        httponly=True, secure=settings.cookie_secure, samesite="lax", path="/api")
    return public_user(user, db)


@router.get("/me", response_model=UserOutput)
def me(db: DB, user: CurrentUser):
    return public_user(user, db)


class PasswordChangeInput(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    actual: SecretStr = Field(min_length=1, max_length=128)
    nueva: SecretStr = Field(min_length=15, max_length=20)


@router.post('/cambiar-contrasena', status_code=204)
def change_password(data: PasswordChangeInput, request: Request, response: Response, db: DB,
                    identity: Annotated[Identity, Depends(current_identity)],
                    settings: Annotated[AuthSettings, Depends(auth_settings)]):
    current = data.actual.get_secret_value()
    new = data.nueva.get_secret_value()
    if current == new:
        raise HTTPException(422, 'La nueva contraseña debe ser diferente.')
    try:
        encoded = hash_password(new)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    authenticated = login(db, identity.user.correo, current)
    if authenticated is None:
        raise HTTPException(401, LOGIN_ERROR)
    lock_email(db, digest(identity.user.correo))
    account = db.get(Usuario, identity.user.id_usuario, with_for_update=True, populate_existing=True)
    if (account is None or not verify_password(account.hash_contrasena, current)
            or db.get(Sesion, digest(authenticated[1])) is None):
        db.execute(delete(Sesion).where(Sesion.token_hash == digest(authenticated[1])))
        db.commit()
        raise HTTPException(401, LOGIN_ERROR)
    account.hash_contrasena = encoded
    db.execute(delete(Sesion).where(Sesion.id_usuario == account.id_usuario))
    db.execute(delete(CambioClavePendiente).where(CambioClavePendiente.id_usuario == account.id_usuario))
    db.commit()
    response.delete_cookie(session_cookie_name(request), path='/api', httponly=True,
                           secure=settings.cookie_secure, samesite='lax')


@router.post("/logout", status_code=204, dependencies=[Depends(protect_mutation)])
def sign_out(request: Request, response: Response, db: DB, identity: Annotated[Identity, Depends(current_identity)],
             settings: Annotated[AuthSettings, Depends(auth_settings)]):
    db.delete(identity.session)
    db.commit()
    response.delete_cookie(session_cookie_name(request), path="/api", httponly=True,
                           secure=settings.cookie_secure, samesite="lax")
