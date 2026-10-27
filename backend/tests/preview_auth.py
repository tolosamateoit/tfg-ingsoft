"""Servidor de QA visual, exclusivamente loopback y datos SINTÉTICOS en memoria.

python -m uvicorn tests.preview_auth:app --host 127.0.0.1 --port 8001
Nunca importa .env ni usa PostgreSQL. No usar para desplegar la demo.
"""

from contextlib import asynccontextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.auth import router
from app.main import private_responses, validation_error
from tests.auth_support import override_database, sqlite_engine


@asynccontextmanager
async def lifespan(app):
    engine = sqlite_engine()
    override_database(app, engine)
    with patch("app.auth.service.lock_email"):
        try:
            yield
        finally:
            engine.dispose()


app = FastAPI(title="QA HU-01 — SINTÉTICO SQLite, sin Supabase", lifespan=lifespan)
app.include_router(router, prefix="/api")
app.add_exception_handler(RequestValidationError, validation_error)
app.middleware("http")(private_responses)
