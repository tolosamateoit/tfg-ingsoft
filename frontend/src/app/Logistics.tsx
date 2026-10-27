import { Status, displayText } from './ui';
import { useEffect, useState } from 'react';
import { operationRequest } from '../services/operations';
import { OrderError } from '../services/orders';
import type { Delivery, PriorityPage, Tracking } from '../services/logistics';
import DeliveryTracking from './DeliveryTracking';

type Props = { restaurant: number; courier: boolean; view?: 'priorities' | 'deliveries'; onSessionExpired: () => void };

export default function Logistics({ restaurant, courier, view = 'deliveries', onSessionExpired }: Props) {
  const [priorities, setPriorities] = useState<PriorityPage | null>(null);
  const [rows, setRows] = useState<Delivery[]>([]);
  const [offset, setOffset] = useState(0);
  const [distances, setDistances] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo completar la operación.');
  }
  async function load(signal?: AbortSignal) {
    setRows(await operationRequest<Delivery[]>(`entregas?offset=${offset}`, undefined, signal));
  }
  async function refreshPriority() {
    const result = await operationRequest<PriorityPage>(`restaurantes/${restaurant}/prioridades`, {}, undefined, 'POST');
    setPriorities(result); setDistances(Object.fromEntries(result.pedidos.map((row) => [row.id_pedido, row.distancia_km])));
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); }
    catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch((failure: unknown) => { if (!controller.signal.aborted) failed(failure); });
    return () => controller.abort();
  }, [offset]);

  async function changeState(id: number, estado: string) {
    const result = await operationRequest<Tracking>(`entregas/${id}/estado`, { estado });
    setSelected(null); await load(); setSelected(result.id_pedido);
  }

  async function assign() {
    const result = await operationRequest<{ entregas: Delivery[]; pendientes: number }>(
      `restaurantes/${restaurant}/entregas/asignar`, {}, undefined, 'POST');
    setNotice(`${result.entregas.length} entrega(s) asignada(s). ${result.pendientes} pedido(s) listo(s) pendiente(s) de repartidor.`);
    setOffset(0);
    setRows(await operationRequest<Delivery[]>('entregas?offset=0'));
    await refreshPriority();
  }

  return <section id="gestion-entregas" className="menu-manager" aria-label="Prioridad y entregas">
    {!courier && view === 'priorities' && <><h2>Orden de atención</h2>
      <button disabled={busy} onClick={() => void run(refreshPriority)}>Calcular y actualizar prioridades</button>
      <p>P = T + D + G. Los valores corresponden al último cálculo; actualizalos para incorporar el tiempo transcurrido.</p>
      {priorities && <><p>Cálculo: {new Date(priorities.calculada_en).toLocaleString('es-AR')}</p>
        {!priorities.pedidos.length && <p>No hay pedidos activos.</p>}
        <div className="catalog-grid">{priorities.pedidos.map((row, index) => <article className="product-card menu-form" key={row.id_pedido}>
          <h3>{index + 1}. Pedido #{row.id_pedido}</h3><p>{row.estado} · Prioridad: {row.puntaje_prioridad}</p>
          <p>T: {row.factores_prioridad.T} · D: {row.factores_prioridad.D} · G: {row.factores_prioridad.G}</p>
          <p>Creado: {new Date(row.fecha_hora).toLocaleString('es-AR')}</p>
          {['Nuevo', 'En preparación', 'Listo'].includes(row.estado) && <form onSubmit={(event) => { event.preventDefault(); void run(async () => {
            await operationRequest(`restaurantes/${restaurant}/pedidos/${row.id_pedido}/distancia`, { distancia_km: distances[row.id_pedido] });
            await refreshPriority();
          }); }}>
            <label htmlFor={`distance-${row.id_pedido}`}>Distancia estimada del pedido #{row.id_pedido} (km)</label>
            <input id={`distance-${row.id_pedido}`} type="number" required min="0" max="999999999.999" step="0.001" disabled={busy}
              value={distances[row.id_pedido] ?? row.distancia_km} onChange={(event) => setDistances({ ...distances, [row.id_pedido]: event.target.value })} />
            <button disabled={busy} type="submit">Guardar distancia del pedido #{row.id_pedido}</button>
          </form>}
        </article>)}</div>
      </>}
    </>}
    {view === 'deliveries' && <><h2>{courier ? 'Tu recorrido de hoy' : 'Seguimiento de entregas'}</h2>
    {!courier && <><p>Se asignan primero los pedidos listos de mayor prioridad, con repartidores disponibles del restaurante.</p>
      <button disabled={busy} onClick={() => void run(assign)}>Asignar pedidos listos por prioridad</button></>}
    <button disabled={busy} onClick={() => void run(() => load())}>Actualizar entregas</button>
    {error && <p role="alert" className="auth-error">{error}</p>}
    {notice && <p role="status" className="menu-notice">{notice}</p>}
    {!rows.length && <p>No hay entregas para mostrar.</p>}
    <div className="catalog-grid">{rows.map((row) => <article className="product-card" key={row.id_entrega}>
      <h3>Entrega #{row.id_entrega} · Pedido #{row.id_pedido}</h3><p><Status value={row.estado}/> · {displayText(row.repartidor)}</p>
      <p>Cliente: {displayText(row.cliente)} · Dirección: {row.direccion_entrega}</p>{row.referencia_local && <p>{row.referencia_local}</p>}
      <div className="menu-actions">
        {courier && row.estado === 'Asignado' && <button disabled={busy} onClick={() => void run(() => changeState(row.id_entrega, 'En camino'))}>Iniciar entrega #{row.id_entrega}</button>}
        {courier && row.estado === 'En camino' && <><button disabled={busy} onClick={() => void run(() => changeState(row.id_entrega, 'Entregado'))}>Marcar entregada #{row.id_entrega}</button>
          <button disabled={busy} onClick={() => void run(() => changeState(row.id_entrega, 'No entregado'))}>Marcar no entregada #{row.id_entrega}</button></>}
        <button disabled={busy} onClick={() => setSelected(row.id_pedido)}>Seguimiento del pedido #{row.id_pedido}</button>
      </div>
    </article>)}</div>
    <div className="menu-actions"><button disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Entregas anteriores</button>
      <button disabled={busy || rows.length < 20} onClick={() => setOffset(offset + 20)}>Más entregas</button></div>
    {selected !== null && <DeliveryTracking key={selected + ':' + rows.find((row) => row.id_pedido === selected)?.estado} order={selected} onSessionExpired={onSessionExpired} />}
    </>}
    {view === 'priorities' && error && <p role="alert" className="auth-error">{error}</p>}
  </section>;
}
