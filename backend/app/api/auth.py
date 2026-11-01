"""Únicos endpoints funcionales de esta etapa: login, sesión y logout."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.auth.config import AuthSettings
from app.auth.dependencies import (
    DB, CurrentUser, Identity, auth_settings, current_identity, protect_mutation, session_cookie_name,
)
from app.auth.security import normalize_email
from app.auth.service import SESSION_TTL, login

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


def public_user(user) -> UserOutput:
    return UserOutput(**{name: getattr(user, name) for name in UserOutput.model_fields})


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
    return public_user(user)


@router.get("/me", response_model=UserOutput)
def me(user: CurrentUser):
    return public_user(user)


@router.post("/logout", status_code=204, dependencies=[Depends(protect_mutation)])
def sign_out(request: Request, response: Response, db: DB, identity: Annotated[Identity, Depends(current_identity)],
             settings: Annotated[AuthSettings, Depends(auth_settings)]):
    db.delete(identity.session)
    db.commit()
    response.delete_cookie(session_cookie_name(request), path="/api", httponly=True,
                           secure=settings.cookie_secure, samesite="lax")
