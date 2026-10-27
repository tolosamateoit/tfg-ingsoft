"""Unidad de trabajo compartida por las dependencias de FastAPI."""

from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import DatabaseConfigurationError
from app.db.engine import build_engine


@lru_cache(maxsize=1)
def get_engine():
    return build_engine()


def get_db():
    try:
        with Session(get_engine(), expire_on_commit=False) as db:
            yield db
    except (SQLAlchemyError, DatabaseConfigurationError):
        # No devolver ni registrar SQL, parámetros, tokens o datos de conexión.
        raise HTTPException(503, "Autenticación temporalmente no disponible.") from None
