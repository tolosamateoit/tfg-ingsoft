export type Priority = {
  id_pedido: number; fecha_hora: string; estado: string; distancia_km: string;
  puntaje_prioridad: string; factores_prioridad: { T: number; D: string; G: string };
};
export type PriorityPage = { calculada_en: string; pedidos: Priority[] };
export type Delivery = {
  id_entrega: number; id_pedido: number; id_repartidor: number; repartidor: string; cliente: string;
  direccion_entrega: string; referencia_local: string | null; estado: string; fecha_asignacion: string;
};
export type Tracking = {
  id_pedido: number; estado_pedido: string; entrega: Delivery | null;
  historial: { id_historial: number; fecha_hora: string; usuario: string; estado: string; detalle: string | null }[];
};
