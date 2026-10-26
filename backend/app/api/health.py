"""Comprobación técnica de comunicación, sin acceso a datos de negocio."""

from typing import Literal

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import DatabaseConfigurationError
from app.db.connection import check_database_connection

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    message: str


@router.get("/health", response_model=HealthResponse, tags=["Comprobación"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", message="El backend está disponible.")


@router.get("/health/database", response_model=HealthResponse, tags=["Comprobación"])
def database_health() -> HealthResponse:
    try:
        available = check_database_connection()
    except DatabaseConfigurationError:
        raise HTTPException(
            status_code=503,
            detail="Configuración de PostgreSQL incompleta o inválida. Revisá el .env del backend y el certificado.",
        ) from None
    except psycopg.Error:
        # El módulo de conexión registra el motivo sanitizado solo en la terminal.
        # El diagnóstico público no expone el error técnico ni datos de conexión.
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar con PostgreSQL. Revisá configuración, certificado, red y estado del proyecto Supabase.",
        ) from None

    if not available:
        raise HTTPException(status_code=503, detail="PostgreSQL no respondió como se esperaba.")
    return HealthResponse(status="ok", message="Conexión con PostgreSQL verificada.")
