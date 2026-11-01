import { cacheScope, invalidateMutation } from './queryCache';
import { OrderError } from './orders';
import { sessionHeaders } from './session';

export async function operationRequest<T>(path: string, body?: object, signal?: AbortSignal, method = body ? 'PUT' : 'GET', timeoutMs = 10000): Promise<T> {
  const requestScope = cacheScope();
  const response = await fetch(`/api/${path}`, {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: await sessionHeaders(!['GET', 'HEAD', 'OPTIONS'].includes(method)),
    body: body ? JSON.stringify(body) : undefined,
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const detail = data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string' ? data.detail : null;
    throw new OrderError(response.status, detail ?? 'No se pudo completar la operación. Actualizá los datos.');
  }
  const result = await response.json() as T;
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) await invalidateMutation(path, requestScope);
  return result;
}

export type Stock = { id_insumo: number; nombre: string; unidad: string; stock_actual: string };
export type Preparation = {
  id_pedido: number; estado: string; version: number;
  historial: { id_historial: number; fecha_hora: string; usuario: string; estado: string; tipo_evento: string; detalle: string | null }[];
  movimientos: { id_movimiento: number; id_insumo: number; nombre: string; unidad: string; cantidad: string; fecha_hora: string; motivo: string | null }[];
};

export type Courier = { id_repartidor: number; nombre: string; zona: string | null; activo: boolean; estado_disponibilidad: string; ultimo_cambio: string | null; entrega_activa: boolean };
export type CourierPage = { id_restaurante: number; abierto: boolean; delivery_disponible: boolean; repartidores: Courier[] };
