import { displayText, Status } from './ui';
import { useEffect, useState } from 'react';
import { operationRequest } from '../services/operations';
import { OrderError } from '../services/orders';
import type { Tracking } from '../services/logistics';

type Props = { order: number; onSessionExpired: () => void };

export default function DeliveryTracking({ order, onSessionExpired }: Props) {
  const [data, setData] = useState<Tracking | null>(null);
  const [error, setError] = useState('');
  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo consultar el seguimiento.');
  }
  async function load(signal?: AbortSignal) {
    setData(await operationRequest<Tracking>(`pedidos/${order}/seguimiento`, undefined, signal));
  }
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch((failure: unknown) => { if (!controller.signal.aborted) failed(failure); });
    return () => controller.abort();
  }, [order]);
  return <section className="menu-manager" aria-label="Seguimiento de entrega">
    <h3>Seguimiento de entrega</h3>
    <button onClick={() => { setError(''); void load().catch(failed); }}>Actualizar seguimiento</button>
    {error && <p role="alert" className="auth-error">{error}</p>}
    {data && <><p><Status value={data.estado_pedido}/></p>
      {data.entrega ? <><p>Entrega #{data.entrega.id_entrega}: {data.entrega.estado}</p>
        <p>Repartidor: {data.entrega.repartidor} · Asignada: {new Date(data.entrega.fecha_asignacion).toLocaleString('es-AR')}</p></> : <p>Entrega todavía sin asignar.</p>}
      <h4>Historial</h4><ul className="timeline">{data.historial.map((event) => <li key={event.id_historial}>{new Date(event.fecha_hora).toLocaleString('es-AR')} · {displayText(event.usuario)} · {event.estado} · {displayText(event.detalle)}</li>)}</ul>
    </>}
  </section>;
}
