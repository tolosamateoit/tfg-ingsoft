import { OrderError } from './orders';

export async function operationRequest<T>(path: string, body?: object, signal?: AbortSignal, method = body ? 'PUT' : 'GET'): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: body ? { 'Content-Type': 'application/json', 'X-CSRF-Protection': '1' } : {},
    body: body ? JSON.stringify(body) : undefined,
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const detail = data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string' ? data.detail : null;
    throw new OrderError(response.status, detail ?? 'No se pudo completar la operación. Actualizá los datos.');
  }
  return await response.json() as T;
}

export type Stock = { id_insumo: number; nombre: string; unidad: string; stock_actual: string };
export type Preparation = {
  id_pedido: number; estado: string; version: number;
  historial: { id_historial: number; fecha_hora: string; usuario: string; estado: string; tipo_evento: string; detalle: string | null }[];
  movimientos: { id_movimiento: number; id_insumo: number; nombre: string; unidad: string; cantidad: string; fecha_hora: string; motivo: string | null }[];
};

export type Courier = { id_repartidor: number; nombre: string; zona: string | null; activo: boolean; estado_disponibilidad: string; ultimo_cambio: string | null };
export type CourierPage = { id_restaurante: number; abierto: boolean; delivery_disponible: boolean; repartidores: Courier[] };
