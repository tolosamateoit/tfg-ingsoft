import { useApiQuery } from '../services/useApiQuery';
import { formatDateTime } from '../services/format';
import { displayText, Status } from './ui';
import { useEffect, useState } from 'react';
import { operationRequest, type CourierPage, type Preparation as PreparationData } from '../services/operations';
import { OrderError } from '../services/orders';

type Props = { restaurant: number; order: number; onSessionExpired: () => void; onChanged: (estado: string) => void };

export default function Preparation({ restaurant, order, onSessionExpired, onChanged }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reason, setReason] = useState('');
  const [repeat, setRepeat] = useState(false);
  const path = `restaurantes/${restaurant}/pedidos/${order}/preparacion`;

  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo conectar con el servidor.');
  }

  const query = useApiQuery<PreparationData>(path, (signal) => operationRequest(path, undefined, signal), onSessionExpired);
  const courierPath = `restaurantes/${restaurant}/repartidores`;
  const couriers = useApiQuery<CourierPage>(courierPath, signal => operationRequest(courierPath, undefined, signal), onSessionExpired, {interval:10000});
  const data = query.data;
  const queryError = query.error?.message;
  useEffect(() => { if (data) onChanged(data.estado); }, [data?.estado]);
  async function load() {
    await query.refetch({cancelRefetch:false,throwOnError:true});
  }
  async function change(estado: string, nueva_preparacion = false) {
    if (!data) return;
    setBusy(true); setError('');
    try {
      const saved = await operationRequest<PreparationData>(path, { estado, version: data.version, nueva_preparacion, motivo: nueva_preparacion ? reason : '' });
      setRepeat(false); setReason(''); onChanged(saved.estado);
    } catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }

  return <section aria-label="Preparación y stock" className="menu-manager">
    <h3>Preparación y stock</h3>
    <button disabled={busy} onClick={() => { setError(''); void load().catch(failed); }}>Actualizar preparación y stock</button>
    {(error || queryError) && <p role="alert" className="auth-error">{error || queryError}</p>}
    {!data ? <p>Cargando preparación…</p> : <>
      <p><Status value={data.estado}/></p>
      <div className="menu-actions">
        {data.estado === 'Nuevo' && <button disabled={busy || !couriers.data?.delivery_disponible} onClick={() => void change('En preparación')}>Iniciar preparación</button>}
        {data.estado === 'En preparación' && <button disabled={busy} onClick={() => void change('Listo')}>Marcar listo</button>}
        {['En preparación', 'Listo'].includes(data.estado) && <button disabled={busy} onClick={() => setRepeat(!repeat)}>Nueva preparación explícita</button>}
      </div>
      {data.estado === 'Nuevo' && couriers.data && !couriers.data.delivery_disponible && <p>{couriers.data.abierto ? 'No hay repartidores disponibles para confirmar el pedido.' : 'El restaurante está cerrado.'}</p>}
      {repeat && <div className="menu-form">
        <p>Esta acción registra otra preparación y vuelve a consumir los insumos. Usala si la preparación anterior se arruinó.</p>
        <label htmlFor={`repeat-reason-${order}`}>Motivo de la nueva preparación</label>
        <input id={`repeat-reason-${order}`} maxLength={500} disabled={busy} value={reason} onChange={(event) => setReason(event.target.value)} />
        <button disabled={busy || !reason.trim()} onClick={() => void change('En preparación', true)}>Confirmar nueva preparación y consumo</button>
      </div>}
      <h4>Historial del pedido</h4>
      <ul className="timeline">{data.historial.map((row) => <li key={row.id_historial}>{formatDateTime(row.fecha_hora)} · {displayText(row.usuario)} · {row.estado}</li>)}</ul>
      <h4>Movimientos de consumo de este pedido</h4>
      {!data.movimientos.length && <p>Todavía no se registró consumo.</p>}
      <ul>{data.movimientos.map((row) => <li key={row.id_movimiento}>{displayText(row.nombre)}: {Number(row.stock_antes).toLocaleString('es-AR', {maximumFractionDigits: 6})} {row.unidad} antes → {Number(row.stock_despues).toLocaleString('es-AR', {maximumFractionDigits: 6})} {row.unidad} después</li>)}</ul>
    </>}
  </section>;
}
