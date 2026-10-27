export type Restaurant = { id_restaurante: number; nombre: string; abierto: boolean; delivery_disponible: boolean };
export type MenuItem = { id_producto: number; nombre: string; precio: string };
export type CustomerMenu = { restaurante: Restaurant; productos: MenuItem[] };
export type OrderSummary = {
  id_pedido: number; id_restaurante: number; restaurante: string; cliente: string;
  fecha_hora: string; estado: string; importe_total: string; medio_pago: string; estado_pago: string;
};
export type Order = OrderSummary & {
  direccion_entrega: string; referencia_local: string | null; zona_entrega: string | null; distancia_km: string;
  detalles: { id_producto: number; nombre: string; cantidad: number; precio_unitario: string; subtotal: string }[];
};
export type OrderInput = {
  correo_cliente: string; direccion_entrega: string; referencia_local: string; zona_entrega: string;
  medio_pago: string; distancia_km: string; detalles: { id_producto: number; cantidad: number }[];
};
export class OrderError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export async function orderRequest<T>(path: string, body?: OrderInput, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
    headers: body ? { 'Content-Type': 'application/json', 'X-CSRF-Protection': '1' } : {},
    body: body ? JSON.stringify(body) : undefined,
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const detail = data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string' ? data.detail : null;
    throw new OrderError(response.status, detail ?? 'No se pudo completar la solicitud. Volvé a intentar.');
  }
  return await response.json() as T;
}
export type OrderPage = { pedidos: OrderSummary[]; total: number; limit: number; offset: number };
