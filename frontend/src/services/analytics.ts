import type { CourierPage, Stock } from './operations';

export type Forecast = {
  estado: string; dias_historial: number | null; pedidos_completados: number | null; dias_validacion: number | null;
  fecha_operativa: string | null; observaciones_evaluadas: number; mae: string | null; asociaciones: string[]; limitaciones: string[];
  predicciones: { id_prediccion: number; id_producto: number; producto: string; periodo_inicio: string; periodo_fin: string;
    demanda_estimada: string; modelo: string; nombre_metrica: string | null; valor_metrica: string | null; generada_en: string; dias: { fecha: string; cantidad: string }[]; explicacion: string; observaciones_evaluadas: number; comparacion_mae: Record<string, string>; mae_referencia: string | null }[];
  insumos: { id_insumo: number; nombre: string; unidad: string; cantidad_necesaria: string; stock_actual: string; faltante: string; reposicion_sugerida: string; explicacion: string }[];
  recetas_faltantes: string[]; productos_sin_ventas: string[];
};
export type DayForecast = {
  estado: string; fecha_operativa: string | null; fecha_seleccionada: string | null;
  fechas_disponibles: { fecha: string; etiqueta: string }[];
  pedidos_estimados: number | null; promedio_pedidos: string | null;
  historial_pedidos: { fecha: string; pedidos: number }[];
  cantidad_faltantes: number; compras_completas: boolean;
  productos: { id_producto: number; nombre: string; cantidad: number; estimacion_original: string;
    historial_ventas: { fecha: string; unidades: number }[] }[];
  insumos: Forecast['insumos']; explicaciones: string[]; aviso: string | null;
};
export type Alert = { id_alerta: number; tipo: string; descripcion: string; valor_observado: string; valor_referencia: string; fecha_hora: string; estado: string; severidad: 'critica' | 'advertencia' };
export type OperationalDashboard = {
  fecha_operativa: string | null; fecha: string | null; primera_fecha: string | null;
  pedidos: number; pedidos_dentro_habitual: number; pedidos_con_demora: number;
  pedidos_confirmados: number; ventas: string; ticket_promedio: string | null; pedidos_entregados: number;
  entrega_minutos: string | null; entregas_con_tiempo: number; entregas_habituales: number;
  tiempos_promedio: { estado: string; minutos: string | null; pedidos: number }[];
  entregas_demoradas: number; entregas_sin_referencia: number;
  productos: { id_producto: number; nombre: string; cantidad: number }[];
  evolucion: { fecha: string; pedidos: number; ventas: string; proporcion: number }[];
  alertas: { clave: string; tipo: 'importe' | 'entrega' | 'stock' | 'demanda' | 'demora'; mensaje: string;
    demoras: { estado: string; minutos: string; habitual: string }[];
    id_pedido: number | null; id_entrega: number | null; fecha_pronostico: string | null }[];
  total_alertas: number; fecha_stock: string | null; aviso_stock: string | null;
};
export type AlertPage = { alertas: Alert[]; total: number; limit: number; offset: number };
export type Metrics = {
  inicio: string; fin: string; referencia_inicio: string; referencia_fin: string;
  promedios: Record<string, string | null>; muestras: Record<string, number>;
  promedios_referencia: Record<string, string | null>; muestras_referencia: Record<string, number>;
  stock: Stock[]; repartidores: CourierPage; alertas: Alert[];
};
