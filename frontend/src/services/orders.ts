import { cacheScope, confirmMutation } from './queryCache';
import { sessionHeaders } from './session';
export type Restaurant = { id_restaurante: number; nombre: string; abierto: boolean; delivery_disponible: boolean };
export type MenuItem = { id_producto: number; nombre: string; precio: string; descripcion?: string | null; imagen_url?: string | null };
export type CustomerMenu = { restaurante: Restaurant; productos: MenuItem[] };
export type OrderSummary = {
  id_pedido: number; id_restaurante: number; restaurante: string; cliente: string;
  fecha_hora: string; estado: string; importe_total: string; medio_pago: string; estado_pago: string; estado_desde: string;
  resumen_productos: string; id_entrega: number | null; id_repartidor: number | null;
  repartidor: string | null; estado_entrega: string | null;
  advertencia_importe: string | null; advertencia_entrega: string | null;
};
export type Order = OrderSummary & {
  direccion_entrega: string; referencia_local: string | null; zona_entrega: string | null; distancia_km: string | null;
  detalles: { id_producto: number; nombre: string; cantidad: number; precio_unitario: string; subtotal: string }[];
  preparacion_minutos: string | null; entrega_minutos: string | null; economia: Record<string, string> | null;
};
export type OrderInput = {
  correo_cliente?: string; direccion_entrega: string; referencia_local: string; zona_entrega: string;
  medio_pago: string; detalles: { id_producto: number; cantidad: number }[];
  distancia_km?: string;
};
export class OrderError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export async function orderRequest<T>(path: string, body?: OrderInput, signal?: AbortSignal): Promise<T> {
  const requestScope = cacheScope();
  const response = await fetch(`/api/${path}`, {
    method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
    headers: await sessionHeaders(Boolean(body)),
    body: body ? JSON.stringify(body) : undefined,
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const detail = data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string' ? data.detail : null;
    throw new OrderError(response.status, detail ?? 'No se pudo completar la solicitud. Volvé a intentar.');
  }
  const result = await response.json() as T;
  if (body) await confirmMutation(path, requestScope, result);
  return result;
}
export type OrderPage = { pedidos: OrderSummary[]; total: number; limit: number; offset: number;
  fecha_operativa: string | null; periodo: 'dia' | 'historial' };

export type OperatingOrder = OrderSummary & {
  version: number; distancia_km: string | null; direccion_entrega: string; referencia_local: string | null; prioridad: import('./logistics').Priority | null;
};
export type OperatingDay = {
  fecha_operativa: string | null; actualizada_en: string; abierto: boolean;
  activos: OperatingOrder[]; listos: OperatingOrder[]; en_entrega: OperatingOrder[]; finalizados: OperatingOrder[];
  total_finalizados: number; limit: number; offset: number;
  repartidores: import('./operations').Courier[];
};
