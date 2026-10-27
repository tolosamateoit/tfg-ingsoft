import { displayText, Status } from './ui';
import { useEffect, useState } from 'react';
import { operationRequest, type CourierPage } from '../services/operations';
import { OrderError } from '../services/orders';

type Props = { restaurant: number | null; onSessionExpired: () => void };

export default function Couriers({ restaurant, onSessionExpired }: Props) {
  const [page, setPage] = useState<CourierPage | null>(null);
  const [selected, setSelected] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const path = restaurant === null ? 'repartidores/me' : `restaurantes/${restaurant}/repartidores`;

  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo conectar con el servidor.');
  }
  async function load(signal?: AbortSignal) {
    const result = await operationRequest<CourierPage>(path, undefined, signal);
    setPage(result); setSelected(Object.fromEntries(result.repartidores.map((row) => [row.id_repartidor, row.estado_disponibilidad])));
  }
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch((failure: unknown) => { if (!controller.signal.aborted) failed(failure); });
    return () => controller.abort();
  }, [restaurant]);

  async function save(id: number) {
    setBusy(true); setError(''); setNotice('');
    try {
      await operationRequest(restaurant === null ? path : `${path}/${id}`, { estado_disponibilidad: selected[id] });
      setNotice('Disponibilidad guardada.');
      await load();
    } catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }

  return <section className="menu-manager" aria-label="Repartidores y disponibilidad">
    <div className="menu-heading"><h2>Repartidores</h2>
      <button disabled={busy} onClick={() => { setError(''); void load().catch(failed); }}>Actualizar repartidores</button></div>
    {error && <p role="alert" className="auth-error">{error}</p>}
    {notice && <p role="status" className="menu-notice">{notice}</p>}
    {!page ? <p>Cargando repartidores…</p> : <>
      <p>Restaurante {page.id_restaurante}: {page.abierto ? 'abierto' : 'cerrado'} · {page.delivery_disponible ? 'Delivery disponible' : 'Delivery no disponible'}</p>
      {!page.repartidores.length && <p>Todavía no hay repartidores asociados a esta cuenta.</p>}
      <div className="catalog-grid">{page.repartidores.map((row) => <article className="product-card menu-form" key={row.id_repartidor}>
        <h3>{displayText(row.nombre)}</h3><p>{row.activo ? 'Cuenta activa' : 'Cuenta inactiva'}{row.zona ? ` · Zona: ${row.zona}` : ''}</p>
        <p><Status value={row.estado_disponibilidad}/></p><p>Último cambio: {row.ultimo_cambio ? new Date(row.ultimo_cambio).toLocaleString('es-AR') : 'Sin cambios registrados'}</p>
        <label htmlFor={`courier-${row.id_repartidor}`}>Disponibilidad de {displayText(row.nombre)}</label>
        <select id={`courier-${row.id_repartidor}`} disabled={busy || !row.activo} value={selected[row.id_repartidor] ?? row.estado_disponibilidad}
          onChange={(event) => setSelected({ ...selected, [row.id_repartidor]: event.target.value })}>
          {!['Disponible', 'Ocupado', 'No disponible'].includes(row.estado_disponibilidad) && <option value={row.estado_disponibilidad}>{row.estado_disponibilidad}</option>}
          <option>Disponible</option><option>Ocupado</option><option>No disponible</option>
        </select>
        <button disabled={busy || !row.activo || selected[row.id_repartidor] === row.estado_disponibilidad} onClick={() => void save(row.id_repartidor)}>Guardar disponibilidad de {displayText(row.nombre)}</button>
      </article>)}</div>
    </>}
  </section>;
}
