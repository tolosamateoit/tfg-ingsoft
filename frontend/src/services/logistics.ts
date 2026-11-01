export type Priority = {
  id_pedido: number; fecha_hora: string; estado: string; distancia_km: string | null;
  puntaje_prioridad: string; factores_prioridad: { T: number; D: string | null; G: string };
  posicion: number; explicacion: string; repartidor: string | null;
  factores: { codigo: string; nombre: string; aporte: string | null; barra: string; detalle: string }[];
  resumen_productos: string;
  advertencia_importe: string | null;
};
export type PriorityPage = { calculada_en: string; pedidos: Priority[] };
export type Delivery = {
  id_entrega: number; id_pedido: number; id_repartidor: number; repartidor: string; cliente: string;
  direccion_entrega: string; referencia_local: string | null; estado: string; fecha_asignacion: string; distancia_km: string | null;
  resumen_productos: string;
  advertencia_entrega: string | null;
};
export type Tracking = {
  id_pedido: number; estado_pedido: string; entrega: Delivery | null;
  historial: { id_historial: number; fecha_hora: string; usuario: string; estado: string; detalle: string | null }[];
};
