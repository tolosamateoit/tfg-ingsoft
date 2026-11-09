import { useApiQuery } from '../services/useApiQuery';
import { formatDateTime } from '../services/format';
import { displayText, Status } from './ui';
import { useState } from 'react';
import { operationRequest } from '../services/operations';
import { OrderError } from '../services/orders';
import type { Tracking } from '../services/logistics';
import WarningBadge from './WarningBadge';

type Props = { order: number; manage?: boolean; onUpdated?: () => void; onSessionExpired: () => void };

export default function DeliveryTracking({ order, manage = false, onUpdated, onSessionExpired }: Props) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function change(estado: string) {
    if (!data?.entrega) return;
    setBusy(true); setError('');
    try {
      await operationRequest<Tracking>(`entregas/${data.entrega.id_entrega}/estado`, { estado });
      onUpdated?.();
    } catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }
  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo consultar el seguimiento.');
  }
  const path = `pedidos/${order}/seguimiento`;
  const query = useApiQuery<Tracking>(path, (signal) => operationRequest(path, undefined, signal), onSessionExpired);
  const data = query.data;
  const queryError = query.error?.message;
  async function load() { await query.refetch({cancelRefetch:false,throwOnError:true}); }
  return <section className="menu-manager" aria-label="Seguimiento de entrega">
    <h3>Seguimiento de entrega</h3>
    <button onClick={() => { setError(''); void load().catch(failed); }}>Actualizar seguimiento</button>
    {(error || queryError) && <p role="alert" className="auth-error">{error || queryError}</p>}
    {data && <><p><Status value={data.estado_pedido}/></p>
      {data.entrega ? <><p>Estado de entrega: {data.entrega.estado}<WarningBadge message={data.entrega.advertencia_entrega}/></p>
        <p>Repartidor asignado: {displayText(data.entrega.repartidor)}</p></> : <p>Entrega todavía sin asignar.</p>}
      {manage && data.entrega && <div className="menu-actions">
        {data.entrega.estado === 'Asignado' && <button disabled={busy} onClick={() => void change('En camino')}>Iniciar entrega</button>}
        {data.entrega.estado === 'En camino' && <><button disabled={busy} onClick={() => void change('Entregado')}>Marcar entregada</button>
          <button disabled={busy} onClick={() => void change('No entregado')}>Marcar no entregada</button></>}
      </div>}
      <h4>Historial</h4><ul className="timeline">{data.historial.map((event) => <li key={event.id_historial}>{formatDateTime(event.fecha_hora)} · {event.usuario && <>{displayText(event.usuario)} · </>}{event.estado}</li>)}</ul>
    </>}
  </section>;
}
