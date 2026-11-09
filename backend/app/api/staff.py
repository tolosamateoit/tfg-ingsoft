"""Gestión de personal del restaurante del propietario autenticado."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from app.auth.dependencies import DB, require_restaurant
from app.auth.security import digest, hash_password
from app.auth.service import lock_email
from app.couriers.schemas import CourierInput
from app.db.models import Usuario
from app.auth.models import Sesion

router = APIRouter(tags=['Personal'])
Owner = Annotated[Usuario, Depends(require_restaurant('propietario'))]
PositiveId = Annotated[int, Path(gt=0)]

@router.get('/restaurantes/{id_restaurante}/personal')
def list_staff(id_restaurante: PositiveId, db: DB, user: Owner):
    return [{'id_usuario': u.id_usuario, 'nombre': u.nombre, 'correo': u.correo, 'activo': u.activo}
            for u in db.scalars(select(Usuario).where(Usuario.id_restaurante == user.id_restaurante, Usuario.rol == 'personal').order_by(Usuario.nombre)).all()]

@router.post('/restaurantes/{id_restaurante}/personal', status_code=201)
def create_staff(id_restaurante: PositiveId, data: CourierInput, db: DB, user: Owner):
    try:
        password = hash_password(data.contrasena.get_secret_value())
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    lock_email(db, digest(data.correo))
    if db.scalar(select(Usuario.id_usuario).where(func.lower(Usuario.correo) == data.correo)):
        raise HTTPException(409, 'No se puede crear una cuenta con ese correo.')
    account = Usuario(id_restaurante=user.id_restaurante, nombre=data.nombre, correo=data.correo,
                      hash_contrasena=password, telefono=data.telefono or None, rol='personal', activo=True)
    try:
        db.add(account)
        db.commit()
        return {'id_usuario': account.id_usuario, 'nombre': account.nombre, 'correo': account.correo, 'activo': account.activo}
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'No se pudo crear la cuenta.') from None

@router.delete('/restaurantes/{id_restaurante}/personal/{id_usuario}')
def deactivate_staff(id_restaurante: PositiveId, id_usuario: PositiveId, db: DB, user: Owner):
    account = db.scalar(select(Usuario).where(Usuario.id_usuario == id_usuario, Usuario.id_restaurante == user.id_restaurante, Usuario.rol == 'personal').with_for_update())
    if account is None:
        raise HTTPException(404, 'Personal no disponible.')
    account.activo = False
    db.execute(delete(Sesion).where(Sesion.id_usuario == account.id_usuario))
    db.commit()
    return {'activo': False}
