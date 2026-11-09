from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, computed_field, model_validator

from app.couriers.schemas import CourierPage
from app.preparation.schemas import StockOutput


class DailyForecast(BaseModel):
    fecha: date
    cantidad: Decimal


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
    dias: list[DailyForecast] = []
    explicacion: str = "Predicción anterior; regenerar para obtener evaluación y detalle diario."
    observaciones_evaluadas: int = 0
    comparacion_mae: dict[str, Decimal] = {}
    mae_referencia: Decimal | None = None


class IngredientNeed(BaseModel):
    id_insumo: int
    nombre: str
    unidad: str
    cantidad_necesaria: Decimal
    stock_actual: Decimal
    faltante: Decimal
    reposicion_sugerida: Decimal = Decimal(0)
    explicacion: str = ""


class ForecastOutput(BaseModel):
    estado: str
    dias_historial: int | None = None
    pedidos_completados: int | None = None
    dias_validacion: int | None = None
    predicciones: list[ForecastItem] = []
    insumos: list[IngredientNeed] = []
    recetas_faltantes: list[str] = []
    productos_sin_ventas: list[str] = []
    fecha_operativa: date | None = None
    observaciones_evaluadas: int = 0
    mae: Decimal | None = None
    asociaciones: list[str] = []
    limitaciones: list[str] = []
    pedidos_estimados_original: Decimal | None = None


class ForecastDateOption(BaseModel):
    fecha: date
    etiqueta: str


class HistoricalSalesDay(BaseModel):
    fecha: date
    unidades: int


class HistoricalOrdersDay(BaseModel):
    fecha: date
    pedidos: int


class PreparationProduct(BaseModel):
    id_producto: int
    nombre: str
    cantidad: int
    estimacion_original: Decimal
    historial_ventas: list[HistoricalSalesDay] = []


class DayForecastOutput(BaseModel):
    estado: str
    fecha_operativa: date | None = None
    fecha_seleccionada: date | None = None
    fechas_disponibles: list[ForecastDateOption] = []
    pedidos_estimados: int | None = None
    promedio_pedidos: Decimal | None = None
    historial_pedidos: list[HistoricalOrdersDay] = []
    cantidad_faltantes: int = 0
    compras_completas: bool = True
    productos: list[PreparationProduct] = []
    insumos: list[IngredientNeed] = []
    explicaciones: list[str] = []
    aviso: str | None = None
    # Evidencia interna conservada para la tesis; no se presenta en la pantalla.
    evaluacion: ForecastOutput | None = None


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
    model_config = ConfigDict(from_attributes=True)
    id_alerta: int
    tipo: str
    descripcion: str
    valor_observado: Decimal
    valor_referencia: Decimal
    fecha_hora: datetime
    estado: str

    @computed_field
    @property
    def severidad(self) -> str:
        # Clasificación visual: no modifica umbrales ni detección de HU-09.
        return "critica" if ((self.tipo == "stock" and self.valor_observado < 0)
                             or self.valor_observado > self.valor_referencia * 2) else "advertencia"


class AlertPage(BaseModel):
    alertas: list[AlertOutput]
    total: int
    limit: int
    offset: int


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
