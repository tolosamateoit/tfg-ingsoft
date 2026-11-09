import { cacheScope, invalidateMutation } from '../services/queryCache';
import { useApiQuery } from '../services/useApiQuery';
import { formatDistance } from '../services/format';
import { Dialog, Status, displayText } from './ui';
import { useState } from 'react';
import { operationRequest } from '../services/operations';
import { OrderError } from '../services/orders';
import type { Delivery, Tracking } from '../services/logistics';
import DeliveryTracking from './DeliveryTracking';
import OrderListing from './OrderListing';
import PriorityBoard from './PriorityBoard';
import CourierPerformance from './CourierPerformance';

type Props = { restaurant: number; courier: boolean; view?: 'priorities' | 'deliveries'; onSessionExpired: () => void };

export default function Logistics({ restaurant, courier, view = 'deliveries', onSessionExpired }: Props) {
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [selectedDate, setSelectedDate] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo completar la operación.');
  }
  const path = `entregas?activos=true&offset=${offset}`;
  const deliveryQuery = useApiQuery<Delivery[]>(path, (signal) => operationRequest(path, undefined, signal), onSessionExpired,
    {enabled:courier && view === 'deliveries'});
  const rows = deliveryQuery.data ?? [];
  const queryError = deliveryQuery.error?.message;
  async function load() {
    if (!courier) { await invalidateMutation(`restaurantes/${restaurant}/entregas`, cacheScope()); return; }
    await deliveryQuery.refetch({cancelRefetch:false,throwOnError:true});
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); }
    catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }
  async function changeState(id: number, estado: string) {
    const result = await operationRequest<Tracking>(`entregas/${id}/estado`, { estado });
    setSelected(null); setSelected(result.id_pedido);
  }

  async function assign() {
    const result = await operationRequest<{ entregas: Delivery[]; pendientes: number }>(
      `restaurantes/${restaurant}/entregas/asignar`, undefined, undefined, 'POST');
    setNotice(`${result.entregas.length} entrega(s) asignada(s). ${result.pendientes} pedido(s) listo(s) pendiente(s) de repartidor.`);
    setOffset(0);
    setRefresh((value) => value + 1);
  }

  return <section id="gestion-entregas" className="menu-manager" aria-label="Prioridad y entregas">
    {courier && <CourierPerformance path="repartidores/me/desempeno" daily selectedDate={selectedDate} onSessionExpired={onSessionExpired}/>}
    {!courier && view === 'priorities' && <PriorityBoard key={restaurant} restaurant={restaurant} onSessionExpired={onSessionExpired}/>}
    {view === 'deliveries' && <><h2>{courier ? 'Pedidos en reparto' : 'Seguimiento de pedidos'}</h2>
    {!courier && <><p>Se asignan repartidores disponibles a los pedidos que llevan más tiempo listos.</p>
      <button disabled={busy} onClick={() => void run(assign)}>Asignar pedidos listos</button></>}
    <button disabled={busy} onClick={() => void run(() => load())}>Actualizar entregas</button>
    {(error || queryError) && <p role="alert" className="auth-error">{error || queryError}</p>}
    {notice && <p role="status" className="menu-notice">{notice}</p>}
    {!courier && <OrderListing key={restaurant} restaurant={restaurant} refresh={refresh} deliveries
      onOpen={setSelected} onSessionExpired={onSessionExpired}/>}
    {courier && <>
    {!rows.length && <p>No hay entregas para mostrar.</p>}
    <div className="catalog-grid">{rows.map((row) => <article className="product-card" key={row.id_entrega}>
      <h3>Entrega #{row.id_entrega} · Pedido #{row.id_pedido}</h3><p><Status value={row.estado}/> · {displayText(row.repartidor)}</p>
      <p>{row.resumen_productos}</p>
      <p>Cliente: {displayText(row.cliente)} · Dirección: {row.direccion_entrega}</p>{row.referencia_local && <p>{row.referencia_local}</p>}
      <p>Distancia estimada: {row.distancia_km === null ? 'Sin confirmar' : `${formatDistance(row.distancia_km)} km`}</p><div className="menu-actions">
        {courier && row.estado === 'Asignado' && <button disabled={busy} onClick={() => void run(() => changeState(row.id_entrega, 'En camino'))}>Iniciar entrega #{row.id_entrega}</button>}
        {courier && row.estado === 'En camino' && <><button disabled={busy} onClick={() => void run(() => changeState(row.id_entrega, 'Entregado'))}>Marcar entregada #{row.id_entrega}</button>
          <button disabled={busy} onClick={() => void run(() => changeState(row.id_entrega, 'No entregado'))}>Marcar no entregada #{row.id_entrega}</button></>}
        <button disabled={busy} onClick={() => setSelected(row.id_pedido)}>Seguimiento del pedido #{row.id_pedido}</button>
      </div>
    </article>)}</div>
    <div className="menu-actions"><button disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Entregas anteriores</button>
      <button disabled={busy || rows.length < 20} onClick={() => setOffset(offset + 20)}>Más entregas</button></div>
    </>}
    {courier && <OrderListing restaurant={null} refresh={refresh} onOpen={setSelected} onDateChange={setSelectedDate} onSessionExpired={onSessionExpired}/>}
    {selected !== null && <Dialog title={`Seguimiento del pedido #${selected}`} busy={false} onClose={() => setSelected(null)}>
      <DeliveryTracking key={selected + ':' + refresh + ':' + rows.find((row) => row.id_pedido === selected)?.estado} order={selected} manage={courier} onUpdated={() => setRefresh((n) => n + 1)} onSessionExpired={onSessionExpired} /></Dialog>}
    </>}
    {view === 'priorities' && error && <p role="alert" className="auth-error">{error}</p>}
  </section>;
}
