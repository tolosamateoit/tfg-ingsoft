from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, model_validator

from app.couriers.schemas import CourierPage
from app.preparation.schemas import StockOutput


class ForecastItem(BaseModel):
    id_prediccion: int
    id_producto: int
    producto: str
    periodo_inicio: date
    periodo_fin: date
    demanda_estimada: Decimal
    modelo: str
    nombre_metrica: str | None
    valor_metrica: Decimal | None
    generada_en: datetime


class IngredientNeed(BaseModel):
    id_insumo: int
    nombre: str
    unidad: str
    cantidad_necesaria: Decimal
    stock_actual: Decimal
    faltante: Decimal


class ForecastOutput(BaseModel):
    estado: str
    dias_historial: int | None = None
    pedidos_completados: int | None = None
    dias_validacion: int | None = None
    predicciones: list[ForecastItem] = []
    insumos: list[IngredientNeed] = []
    recetas_faltantes: list[str] = []
    productos_sin_ventas: list[str] = []


class PeriodInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inicio: date
    fin: date

    @model_validator(mode="after")
    def valid_period(self):
        if self.fin < self.inicio:
            raise ValueError("El fin debe ser posterior o igual al inicio.")
        return self


class AlertOutput(BaseModel):
    id_alerta: int
    tipo: str
    descripcion: str
    valor_observado: Decimal
    valor_referencia: Decimal
    fecha_hora: datetime
    estado: str


class MetricsOutput(BaseModel):
    inicio: date
    fin: date
    referencia_inicio: date
    referencia_fin: date
    promedios: dict[str, Decimal | None]
    muestras: dict[str, int]
    promedios_referencia: dict[str, Decimal | None]
    muestras_referencia: dict[str, int]
    stock: list[StockOutput]
    repartidores: CourierPage
    alertas: list[AlertOutput]
