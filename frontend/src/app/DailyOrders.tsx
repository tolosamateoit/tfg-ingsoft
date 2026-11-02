import { useApiQuery } from '../services/useApiQuery';
import { useEffect, useRef, useState } from 'react';
import { formatCalendarDate, formatDateTime, formatMoney } from '../services/format';
import { operationRequest, type Courier } from '../services/operations';
import { OrderError, type OperatingDay, type OperatingOrder } from '../services/orders';
import { Dialog, Status } from './ui';
import WarningBadge from './WarningBadge';
import PriorityExplanation from './PriorityExplanation';
import { apiKey, queryClient } from '../services/queryCache';

type CardProps = { row: OperatingOrder; couriers: Courier[]; busy: boolean;
  confirmedState?: string;
  onOpen: (id: number) => void; onState: (row: OperatingOrder, state: string) => void;
  onReject: (row: OperatingOrder) => void; onAssign: (row: OperatingOrder, courier: number, distance?: string) => void;
  onDelivery: (row: OperatingOrder, state: string) => void; onDistance: (row: OperatingOrder, distance: string) => void };

export function DailyOrderCard({ row, couriers, busy, confirmedState, onOpen, onState, onReject, onAssign, onDelivery, onDistance }: CardProps) {
  const [courier, setCourier] = useState('');
  const [distance, setDistance] = useState('');
  const validCourier = couriers.some((c) => c.id_repartidor === Number(courier));
  return <article className={`daily-order${row.prioridad ? ' daily-order--active' : ''}`}>
    <header><div className="daily-order-title">{row.prioridad && <span className="daily-order-rank">Prioridad <strong>{row.prioridad.posicion}</strong></span>}
      <h4>Pedido #{row.id_pedido}<WarningBadge message={row.advertencia_importe}/></h4></div><Status value={confirmedState ?? row.estado}/></header>
    {confirmedState && <p role="status">Cambio guardado. Actualizando pedido…</p>}
    <p className="daily-order-time">{formatDateTime(row.fecha_hora)}</p>
    <p className="daily-order-products">{row.resumen_productos || 'Sin productos registrados'}</p>
    <div className="daily-order-info"><strong>{formatMoney(row.importe_total)}</strong>
      {row.repartidor && <span>Repartidor: {row.repartidor}<WarningBadge message={row.advertencia_entrega}/></span>}</div>
    {row.prioridad && <details className="daily-order-why"><summary>¿Por qué esta prioridad?</summary><PriorityExplanation priority={row.prioridad}/></details>}
    {(row.prioridad || row.estado === 'Listo' && row.distancia_km !== null) && <details className="daily-order-distance">
      <summary>Modificar distancia</summary><form onSubmit={(event) => { event.preventDefault();
        const value = new FormData(event.currentTarget).get('distancia'); if (typeof value === 'string') onDistance(row, value);
      }}><label htmlFor={`order-distance-${row.id_pedido}`}>Distancia de entrega (km)</label><div>
        <input id={`order-distance-${row.id_pedido}`} name="distancia" type="number" min="0" max="5" step="0.001" required
          key={`${row.id_pedido}:${row.distancia_km}`} defaultValue={row.distancia_km ?? ''} disabled={busy}/>
        <button disabled={busy}>Guardar distancia</button></div></form></details>}
    <div className="daily-order-actions">
      {row.estado === 'Nuevo' && <><button className="primary-button" disabled={busy} onClick={() => onState(row, 'En preparación')}>Confirmar pedido</button>
        <button className="order-reject" disabled={busy} onClick={() => onReject(row)}>Rechazar</button></>}
      {row.estado === 'En preparación' && <button className="primary-button" disabled={busy} onClick={() => onState(row, 'Listo')}>Marcar como listo</button>}
      {row.estado === 'Asignado' && <button disabled={busy} onClick={() => onDelivery(row, 'En camino')}>Iniciar entrega</button>}
      {row.estado === 'En camino' && <><button className="primary-button" disabled={busy} onClick={() => onDelivery(row, 'Entregado')}>Finalizar entrega</button>
        <button disabled={busy} onClick={() => onDelivery(row, 'No entregado')}>Marcar no entregada</button></>}
      <button className="daily-order-detail" onClick={() => onOpen(row.id_pedido)}>Ver detalle</button>
    </div>
    {row.estado === 'Listo' && <form className="daily-order-dispatch" onSubmit={(event) => {
      event.preventDefault(); if (validCourier) onAssign(row, Number(courier), row.distancia_km === null ? distance : undefined);
    }}><label htmlFor={`dispatch-courier-${row.id_pedido}`}>Repartidor disponible</label>
      <div><select id={`dispatch-courier-${row.id_pedido}`} value={validCourier ? courier : ''} disabled={busy || !couriers.length}
        required onChange={(event) => setCourier(event.target.value)}><option value="">Elegí un repartidor</option>
        {couriers.map((c) => <option key={c.id_repartidor} value={c.id_repartidor}>{c.nombre}</option>)}</select>
        <button className="primary-button" disabled={busy || !validCourier}>Enviar a entrega</button></div>
      {row.distancia_km === null && <><label htmlFor={`dispatch-distance-${row.id_pedido}`}>Distancia de entrega (km)</label>
        <input id={`dispatch-distance-${row.id_pedido}`} type="number" min="0" max="5" step="0.001" required value={distance}
          disabled={busy} onChange={(event) => setDistance(event.target.value)}/>
        <p className="daily-order-hint">Este registro no tiene una distancia válida; ingresá el dato real para calcular el envío.</p></>}
      {!couriers.length && <p className="daily-order-hint">No hay repartidores disponibles en este momento.</p>}
    </form>}
  </article>;
}

type ViewProps = { data: OperatingDay; busy: boolean; onOpen: (id:number) => void;
  pending?: Record<number, {state:string; revision:number}>;
  onState: CardProps['onState']; onReject: CardProps['onReject']; onAssign: CardProps['onAssign']; onDelivery: CardProps['onDelivery'];
  onDistance: CardProps['onDistance'];
  onPage: (offset:number) => void };

export function DailyOrdersView({data, busy, pending = {}, onPage, ...actions}: ViewProps) {
  const cards = (rows: OperatingOrder[]) => <div className="daily-orders-grid">{rows.map((row) => <DailyOrderCard key={row.id_pedido}
    row={row} couriers={data.repartidores} busy={busy || Boolean(pending[row.id_pedido])}
    confirmedState={pending[row.id_pedido]?.state} {...actions}/>)}</div>;
  return <div className="daily-orders-board" aria-busy={busy}>
    <div className="daily-orders-caption"><p>{data.fecha_operativa ? `Día operativo: ${formatCalendarDate(data.fecha_operativa)}` : 'Sin pedidos registrados'}</p>
      <span>Actualización automática cada 30 segundos</span></div>
    <section aria-labelledby="orders-active-title"><h3 id="orders-active-title">Para atender primero <span>{data.activos.length}</span></h3>
      {data.activos.length ? cards(data.activos) : <p className="daily-orders-empty">¡Todo al día! No hay pedidos por preparar.</p>}</section>
    {data.listos.length > 0 && <section aria-labelledby="orders-ready-title"><h3 id="orders-ready-title">Listos para entregar <span>{data.listos.length}</span></h3>{cards(data.listos)}</section>}
    {data.en_entrega.length > 0 && <section aria-labelledby="orders-delivery-title"><h3 id="orders-delivery-title">En reparto <span>{data.en_entrega.length}</span></h3>{cards(data.en_entrega)}</section>}
    {data.total_finalizados > 0 && <details className="daily-orders-completed"><summary>Finalizados y rechazados ({data.total_finalizados})</summary>
      {cards(data.finalizados)}<div className="menu-actions" aria-label="Paginación de finalizados">
        <button disabled={busy || data.offset === 0} onClick={() => onPage(Math.max(0, data.offset - data.limit))}>Anteriores</button>
        <span>Página {Math.floor(data.offset / data.limit) + 1} de {Math.ceil(data.total_finalizados / data.limit)}</span>
        <button disabled={busy || data.offset + data.limit >= data.total_finalizados} onClick={() => onPage(data.offset + data.limit)}>Siguientes</button>
      </div></details>}
  </div>;
}

type Props = { restaurant:number; refresh:number; onOpen:(id:number)=>void; onSessionExpired:()=>void };
export default function DailyOrders({restaurant, onOpen, onSessionExpired}: Props) {
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Record<number, {state:string; revision:number}>>({});
  const [rejecting, setRejecting] = useState<OperatingOrder | null>(null);
  const locked = useRef(false);
  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error && failure.name !== 'TimeoutError' ? failure.message : 'No se pudieron actualizar los pedidos. Volvé a intentar.');
  }
  const path = `restaurantes/${restaurant}/pedidos/operacion?offset=${offset}`;
  const query = useApiQuery<OperatingDay>(path,
    (signal) => operationRequest(path, undefined, signal, 'GET', 30000), onSessionExpired, {interval:30_000});
  const data = query.data;
  async function load() { await query.refetch({cancelRefetch:false, throwOnError:true}); }
  useEffect(() => {
    if (data && offset > 0 && offset >= data.total_finalizados) setOffset(0);
  }, [data, offset]);
  useEffect(() => { setError(query.error?.message ?? ''); }, [query.error]);
  useEffect(() => {
    const revision = queryClient.getQueryState(apiKey(path))?.dataUpdateCount ?? 0;
    setPending(current => Object.fromEntries(Object.entries(current).filter(([, row]) => row.revision >= revision)));
  }, [query.dataUpdatedAt, path]);
  async function mutate(row: OperatingOrder, action: () => Promise<unknown>) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError('');
    try {
      const result = await action() as {estado?:string; estado_pedido?:string; entregas?:unknown[]};
      const state = queryClient.getQueryState(apiKey(path));
      if (state?.fetchStatus === 'fetching' || state?.isInvalidated) {
        setPending(current => ({...current, [row.id_pedido]: {
          state:result.estado_pedido ?? result.estado ?? (result.entregas ? 'Asignado' : row.estado),
          revision:state.dataUpdateCount,
        }}));
      }
      setRejecting(null);
    }
    catch(failure) { failed(failure); setRejecting(null); try { await load(); } catch { /* Se conserva el error de la acción y la última lectura. */ } }
    finally { locked.current = false; setBusy(false); }
  }
  const state = (row:OperatingOrder, estado:string) => void mutate(row, () => operationRequest(
    `restaurantes/${restaurant}/pedidos/${row.id_pedido}/preparacion`, {estado,version:row.version}));
  const assign = (row:OperatingOrder, id_repartidor:number, distancia_km?:string) => void mutate(row, () => operationRequest(
    `restaurantes/${restaurant}/entregas/asignar`, {id_pedido:row.id_pedido,id_repartidor,version:row.version,...(distancia_km !== undefined ? {distancia_km} : {})}, undefined, 'POST'));
  const delivery = (row:OperatingOrder, estado:string) => { if (row.id_entrega !== null) void mutate(row, () => operationRequest(`entregas/${row.id_entrega}/estado`, {estado})); };
  const distance = (row:OperatingOrder, value:string) => {
    if (row.distancia_km !== null && Number(row.distancia_km) === Number(value)) return;
    void mutate(row, () => operationRequest(`restaurantes/${restaurant}/pedidos/${row.id_pedido}/distancia`, {distancia_km:value}));
  };
  return <>
    {error && <p role="alert" className="auth-error">{error} <button disabled={busy} onClick={() => void load().then(() => setError('')).catch(failed)}>Actualizar</button></p>}
    {busy && <p role="status" className="daily-orders-saving">Guardando y actualizando pedidos…</p>}
    {data ? <DailyOrdersView data={data} busy={busy} pending={pending} onOpen={onOpen} onState={state} onReject={setRejecting}
      onAssign={assign} onDelivery={delivery} onDistance={distance} onPage={setOffset}/> : !error && <p role="status">Cargando los pedidos del día…</p>}
    {rejecting && <Dialog title={`¿Rechazar pedido #${rejecting.id_pedido}?`} busy={busy} onClose={() => setRejecting(null)}>
      <p>El pedido quedará cancelado y se conservará en el historial.</p><div className="menu-actions">
        <button disabled={busy} onClick={() => setRejecting(null)}>Volver</button>
        <button className="order-reject" disabled={busy} onClick={() => state(rejecting, 'Cancelado')}>Rechazar pedido</button>
      </div></Dialog>}
  </>;
}
