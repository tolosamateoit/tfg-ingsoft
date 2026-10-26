from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(
    title="Demo académica · Pedidos y delivery",
    description="Base inicial de la API con comprobación de conexión a PostgreSQL. Sin funcionalidades de negocio.",
    version="0.1.0",
)

app.include_router(health_router, prefix="/api")
