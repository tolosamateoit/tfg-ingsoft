import { useEffect, useState } from 'react';
import { formatDateTime, formatDistance } from '../services/format';
import { operationRequest } from '../services/operations';
import { OrderError } from '../services/orders';
import type { PriorityPage } from '../services/logistics';
import { Status } from './ui';
import WarningBadge from './WarningBadge';
import Orders from './Orders';

type Props = { restaurant: number; onSessionExpired: () => void };
type DetailsProps = { page: PriorityPage; busy?: boolean;
  onDistance?: (order: number, distance: string) => void; onOpen?: (order: number) => void };

export function PriorityDetails({ page, busy = false, onDistance, onOpen }: DetailsProps) {
  return <div className="priority-board">
    <header className="priority-heading"><h2>¿Qué pedido atendemos primero?</h2>
      <p>Primero los pedidos nuevos que esperan entrar en preparación.</p></header>
    {!page.pedidos.length ? <p className="priority-empty">¡Todo al día! No hay pedidos nuevos esperando preparación.</p> :
      <ol className="priority-list" aria-label="Ranking de ingreso a preparación">{page.pedidos.map((row) =>
        <li className={`priority-card priority-card--${Math.min(row.posicion, 4)}`} key={row.id_pedido}>
          <div className="priority-card-heading"><span className="priority-position"><span>Prioridad</span><strong>{row.posicion}</strong></span>
            <div className="priority-order-heading"><h3>Pedido #{row.id_pedido}<WarningBadge message={row.advertencia_importe}/></h3>
              <span>{formatDateTime(row.fecha_hora)}</span></div><Status value={row.estado}/></div>
          <p className="priority-products">{row.resumen_productos || 'Sin productos registrados'}</p>
          <p className="priority-reason">{row.explicacion}</p>
          {row.repartidor && <p className="priority-courier">Repartidor: {row.repartidor}</p>}
          {row.distancia_km !== null && Number(row.distancia_km) > 5 && <p className="priority-distance-note">La distancia registrada supera la cobertura de 5 km.</p>}
          <div className="priority-actions"><button type="button" onClick={() => onOpen?.(row.id_pedido)}>Ver pedido</button>
          <details className="priority-breakdown"><summary>Por qué está en esta posición</summary>
            <div className="priority-factors">{row.factores.map((factor) => <div className="priority-factor" key={factor.codigo}>
              <div><strong>{factor.nombre}</strong><span>{factor.codigo === 'D' && row.distancia_km !== null
                ? `${formatDistance(row.distancia_km)} km registrados` : factor.detalle}</span></div>
              {factor.aporte === null ? <p>Sin datos.</p> :
                <div className="priority-factor-track"><span className={`priority-factor-bar priority-factor--${factor.codigo}`} style={{ width: `${factor.barra}%` }}/></div>}
            </div>)}</div>
            <p className="priority-factor-note">Las barras muestran el aporte de cada factor. En empate, va primero el pedido más antiguo.</p>
            {['Nuevo', 'En preparación', 'Listo'].includes(row.estado) && <form className="priority-distance-form" onSubmit={(event) => {
              event.preventDefault(); const value = new FormData(event.currentTarget).get('distancia_km');
              if (typeof value === 'string') onDistance?.(row.id_pedido, value);
            }}><label htmlFor={`priority-distance-${row.id_pedido}`}>Modificar distancia de entrega (hasta 5 km)</label>
              <div><input id={`priority-distance-${row.id_pedido}`} name="distancia_km" key={`${row.id_pedido}:${row.distancia_km}`}
                type="number" min="0" max="5" step="0.001" required disabled={busy}
                defaultValue={row.distancia_km ?? ''} placeholder="Distancia en km"/>
                <button disabled={busy}>Guardar distancia</button></div>
            </form>}
          </details></div>
        </li>)}</ol>}
    <p className="priority-updated">Actualizado: {formatDateTime(page.calculada_en)} · Revisión automática cada 30 segundos.</p>
  </div>;
}

export default function PriorityBoard({ restaurant, onSessionExpired }: Props) {
  const [page, setPage] = useState<PriorityPage | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [order, setOrder] = useState<number | null>(null);
  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error && failure.name !== 'TimeoutError' ? failure.message : 'No se pudo actualizar el orden. Volvé a intentar.');
  }
  useEffect(() => {
    const controller = new AbortController();
    let running = false;
    async function update() {
      if (running || document.hidden || controller.signal.aborted) return;
      running = true;
      try {
        const result = await operationRequest<PriorityPage>(`restaurantes/${restaurant}/prioridades`, undefined, controller.signal, 'GET', 30000);
        if (!controller.signal.aborted) { setPage(result); setError(''); }
      } catch (failure) { if (!controller.signal.aborted) failed(failure); }
      finally { running = false; }
    }
    void update();
    const timer = window.setInterval(() => void update(), 30000);
    const focused = () => void update();
    window.addEventListener('focus', focused);
    document.addEventListener('visibilitychange', focused);
    return () => { controller.abort(); window.clearInterval(timer); window.removeEventListener('focus', focused); document.removeEventListener('visibilitychange', focused); };
  }, [restaurant, revision]);
  async function distance(id: number, value: string) {
    const current = page?.pedidos.find((row) => row.id_pedido === id)?.distancia_km;
    if (current !== null && current !== undefined && Number(value) === Number(current)) return;
    setBusy(true); setError('');
    try {
      await operationRequest(`restaurantes/${restaurant}/pedidos/${id}/distancia`, { distancia_km: value });
      setRevision((n) => n + 1);
    } catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }
  return <>
    <div className="priority-toolbar"><button disabled={busy} onClick={() => setRevision((n) => n + 1)}>Actualizar orden</button></div>
    {error && <p role="alert" className="auth-error">{error}{page && ' Se muestra la última consulta disponible.'}</p>}
    {page ? <PriorityDetails page={page} busy={busy} onDistance={(id, value) => void distance(id, value)} onOpen={setOrder}/>
      : !error && <p role="status">Ordenando los pedidos pendientes…</p>}
    {order !== null && <Orders key={order} restaurant={restaurant} view="detail" initialOrder={order}
      onCloseDetail={() => { setOrder(null); setRevision((n) => n + 1); }} onSessionExpired={onSessionExpired}/>}
  </>;
}
