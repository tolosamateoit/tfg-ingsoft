import { displayText, Status } from './ui';
import { useEffect, useState } from 'react';
import { operationRequest, type Preparation as PreparationData, type Stock } from '../services/operations';
import { OrderError } from '../services/orders';

type Props = { restaurant: number; order: number; onSessionExpired: () => void; onChanged: (estado: string) => void };

export default function Preparation({ restaurant, order, onSessionExpired, onChanged }: Props) {
  const [data, setData] = useState<PreparationData | null>(null);
  const [stock, setStock] = useState<Stock[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reason, setReason] = useState('');
  const [repeat, setRepeat] = useState(false);
  const path = `restaurantes/${restaurant}/pedidos/${order}/preparacion`;

  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo conectar con el servidor.');
  }

  async function load(signal?: AbortSignal) {
    const [preparation, inventory] = await Promise.all([
      operationRequest<PreparationData>(path, undefined, signal),
      operationRequest<Stock[]>(`restaurantes/${restaurant}/stock`, undefined, signal),
    ]);
    setData(preparation); setStock(inventory); onChanged(preparation.estado);
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch((failure: unknown) => { if (!controller.signal.aborted) failed(failure); });
    return () => controller.abort();
  }, [restaurant, order]);

  async function change(estado: string, nueva_preparacion = false) {
    if (!data) return;
    setBusy(true); setError('');
    try {
      const saved = await operationRequest<PreparationData>(path, { estado, version: data.version, nueva_preparacion, motivo: nueva_preparacion ? reason : '' });
      setData(saved); setRepeat(false); setReason(''); onChanged(saved.estado);
      setStock(await operationRequest<Stock[]>(`restaurantes/${restaurant}/stock`));
    } catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }

  return <section aria-label="Preparación y stock" className="menu-manager">
    <h3>Preparación y stock</h3>
    <button disabled={busy} onClick={() => { setError(''); void load().catch(failed); }}>Actualizar preparación y stock</button>
    {error && <p role="alert" className="auth-error">{error}</p>}
    {!data ? <p>Cargando preparación…</p> : <>
      <p><Status value={data.estado}/></p>
      <div className="menu-actions">
        {data.estado === 'Nuevo' && <button disabled={busy} onClick={() => void change('En preparación')}>Iniciar preparación</button>}
        {data.estado === 'En preparación' && <button disabled={busy} onClick={() => void change('Listo')}>Marcar listo</button>}
        {['En preparación', 'Listo'].includes(data.estado) && <button disabled={busy} onClick={() => setRepeat(!repeat)}>Nueva preparación explícita</button>}
      </div>
      {repeat && <div className="menu-form">
        <p>Esta acción registra otra preparación y vuelve a consumir los insumos. Usala si la preparación anterior se arruinó.</p>
        <label htmlFor={`repeat-reason-${order}`}>Motivo de la nueva preparación</label>
        <input id={`repeat-reason-${order}`} maxLength={500} disabled={busy} value={reason} onChange={(event) => setReason(event.target.value)} />
        <button disabled={busy || !reason.trim()} onClick={() => void change('En preparación', true)}>Confirmar nueva preparación y consumo</button>
      </div>}
      <h4>Historial del pedido</h4>
      <ul className="timeline">{data.historial.map((row) => <li key={row.id_historial}>{new Date(row.fecha_hora).toLocaleString('es-AR')} · {displayText(row.usuario)} · {row.estado} · {displayText(row.detalle)}</li>)}</ul>
      <h4>Movimientos de consumo de este pedido</h4>
      {!data.movimientos.length && <p>Todavía no se registró consumo.</p>}
      <ul>{data.movimientos.map((row) => <li key={row.id_movimiento}>{displayText(row.nombre)}: {row.cantidad} {row.unidad} · {new Date(row.fecha_hora).toLocaleString('es-AR')} · {displayText(row.motivo)}</li>)}</ul>
    </>}
    <h4>Stock actual del restaurante</h4>
    {stock.some((row) => Number(row.stock_actual) < 0) && <p role="status" className="auth-error">Hay insumos con stock negativo.</p>}
    <ul>{stock.map((row) => <li key={row.id_insumo}>{displayText(row.nombre)}: {row.stock_actual} {row.unidad}</li>)}</ul>
  </section>;
}
