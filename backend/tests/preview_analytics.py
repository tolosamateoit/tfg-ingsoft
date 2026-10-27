"""QA visual HU-08/HU-09 con historial SINTÉTICO local descartable, nunca Supabase.

python -m uvicorn tests.preview_analytics:app --host 127.0.0.1 --port 8002
"""

from contextlib import asynccontextmanager, contextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.auth.database import get_db
from app.main import private_responses, validation_error
from tests.preview_operations import lifespan as operations_lifespan
from tests import preview_operations
from tests.test_analytics import historical_orders, indicator_history


@asynccontextmanager
async def lifespan(app):
    async with operations_lifespan(app):
        with contextmanager(app.dependency_overrides[get_db])() as db:
            historical_orders(db)
            indicator_history(db)
        with patch("app.analytics.forecast.lock_order_relations"), patch("app.analytics.metrics.lock_order_relations"):
            yield


app = FastAPI(title="QA HU-08/HU-09 — SINTÉTICO SQLite, sin Supabase", lifespan=lifespan)
for router in (auth_router, analytics_router, preview_operations.menu_router, preview_operations.orders_router,
               preview_operations.preparation_router, preview_operations.couriers_router, preview_operations.logistics_router):
    app.include_router(router, prefix="/api")
app.add_exception_handler(RequestValidationError, validation_error)
app.middleware("http")(private_responses)
