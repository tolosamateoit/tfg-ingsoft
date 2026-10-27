import type { CourierPage, Stock } from './operations';

export type Forecast = {
  estado: string; dias_historial: number | null; pedidos_completados: number | null; dias_validacion: number | null;
  predicciones: { id_prediccion: number; id_producto: number; producto: string; periodo_inicio: string; periodo_fin: string;
    demanda_estimada: string; modelo: string; nombre_metrica: string | null; valor_metrica: string | null; generada_en: string }[];
  insumos: { id_insumo: number; nombre: string; unidad: string; cantidad_necesaria: string; stock_actual: string; faltante: string }[];
  recetas_faltantes: string[]; productos_sin_ventas: string[];
};
export type Alert = { id_alerta: number; tipo: string; descripcion: string; valor_observado: string; valor_referencia: string; fecha_hora: string; estado: string };
export type Metrics = {
  inicio: string; fin: string; referencia_inicio: string; referencia_fin: string;
  promedios: Record<string, string | null>; muestras: Record<string, number>;
  promedios_referencia: Record<string, string | null>; muestras_referencia: Record<string, number>;
  stock: Stock[]; repartidores: CourierPage; alertas: Alert[];
};
