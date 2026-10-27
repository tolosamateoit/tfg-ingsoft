"""QA HU-10/HU-11 con datos SINTÉTICOS locales descartables, nunca Supabase.

python -m uvicorn tests.preview_management:app --host 127.0.0.1 --port 8002
"""

import asyncio

from app.api.dashboard import router as dashboard_router
from app.api.support import router as support_router
from tests.preview_analytics import app

app.title = "QA HU-10/HU-11 — SINTÉTICO SQLite, sin Supabase"
app.include_router(dashboard_router, prefix="/api")
app.include_router(support_router, prefix="/api")

# SQLite no tiene los advisory locks de PostgreSQL. Serializar las escrituras
# de esta fixture evita carreras del doble montaje de React en desarrollo.
qa_write_lock = asyncio.Lock()


@app.middleware("http")
async def serialize_qa_mutations(request, call_next):
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        async with qa_write_lock:
            return await call_next(request)
    return await call_next(request)
