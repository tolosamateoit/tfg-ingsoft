from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.menu import router as menu_router
from app.api.orders import router as orders_router
from app.api.preparation import router as preparation_router
from app.api.couriers import router as couriers_router
from app.api.logistics import router as logistics_router
from app.api.analytics import router as analytics_router
from app.api.dashboard import router as dashboard_router
from app.api.support import router as support_router
from app.api.staff import router as staff_router

app = FastAPI(
    title="Demo académica · Pedidos y delivery",
    description="Demo académica. Autenticación y gestión de productos y recetas por restaurante.",
    version="0.4.0",
)

app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(menu_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(preparation_router, prefix="/api")
app.include_router(couriers_router, prefix="/api")
app.include_router(logistics_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(support_router, prefix="/api")
app.include_router(staff_router, prefix="/api")


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # FastAPI incluye input en su respuesta predeterminada; puede contener contraseñas.
    return JSONResponse(status_code=422, content={"detail": "Datos de solicitud inválidos."})


@app.middleware("http")
async def private_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response
