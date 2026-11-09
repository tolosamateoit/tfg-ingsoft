import { useApiQuery } from '../services/useApiQuery';
import CourierPerformance from './CourierPerformance';
import AccountRecovery from './AccountRecovery';
import { formatDateTime } from '../services/format';
import { Dialog, displayText, Status } from './ui';
import { useEffect, useState } from 'react';
import { operationRequest, type CourierPage } from '../services/operations';
import { OrderError } from '../services/orders';
import { formatMoney } from '../services/menu';

type Props = { restaurant: number | null; owner?: boolean; onSessionExpired: () => void };

export default function Couriers({ restaurant, owner = false, onSessionExpired }: Props) {
  const [selected, setSelected] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [creating, setCreating] = useState(false);
  const [rates, setRates] = useState<{ costo_fijo_entrega: string; costo_por_km: string } | null>(null);
  const path = restaurant === null ? 'repartidores/me' : `restaurantes/${restaurant}/repartidores`;

  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo conectar con el servidor.');
  }
  const query = useApiQuery<CourierPage>(path, (signal) => operationRequest(path, undefined, signal), onSessionExpired);
  const page = query.data;
  const ratePath = `restaurantes/${restaurant}/tarifas`;
  const rateQuery = useApiQuery<{ costo_fijo_entrega:string; costo_por_km:string }>(ratePath,
    (signal) => operationRequest(ratePath, undefined, signal), onSessionExpired, {enabled:owner && restaurant !== null});
  useEffect(() => { if (page) setSelected(Object.fromEntries(page.repartidores.map((row) => [row.id_repartidor, row.estado_disponibilidad]))); }, [page]);
  useEffect(() => { if (rateQuery.data) setRates(rateQuery.data); }, [rateQuery.data]);
  const queryError = query.error?.message ?? rateQuery.error?.message;
  async function load() { await query.refetch({cancelRefetch:false,throwOnError:true}); }

  async function save(id: number) {
    setBusy(true); setError(''); setNotice('');
    try {
      await operationRequest(restaurant === null ? path : `${path}/${id}`, { estado_disponibilidad: selected[id] });
      setNotice('Disponibilidad guardada.');
    } catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }

  return <section className="menu-manager" aria-label="Repartidores y disponibilidad">
    <div className="menu-heading"><h2>Repartidores</h2>
      <button disabled={busy} onClick={() => { setError(''); void load().catch(failed); }}>Actualizar repartidores</button></div>
    {(error || queryError) && <p role="alert" className="auth-error">{error || queryError}</p>}
    {notice && <p role="status" className="menu-notice">{notice}</p>}
    {owner && <><button className="primary-button" disabled={busy} onClick={() => { setError(''); setCreating(true); }}>Incorporar repartidor</button>
      {rates && <form className="menu-form menu-editor" onSubmit={(event) => { event.preventDefault(); setBusy(true); setError(''); setNotice('');
        void operationRequest(`restaurantes/${restaurant}/tarifas`, rates).then(() => setNotice('Tarifas guardadas. Se aplicarán a las nuevas asignaciones.')).catch(failed).finally(() => setBusy(false));
      }}><h3>Tarifas de entrega del restaurante</h3><p>Todos los repartidores utilizan estas tarifas. Las entregas asignadas conservan su costo guardado.</p><fieldset disabled={busy}>
        <label htmlFor="delivery-fixed">Costo fijo de entrega</label><input id="delivery-fixed" type="number" min="0" step="0.01" required value={rates.costo_fijo_entrega} onChange={(e) => setRates({ ...rates, costo_fijo_entrega: e.target.value })}/>
        <label htmlFor="delivery-km">Costo por kilómetro</label><input id="delivery-km" type="number" min="0" step="0.01" required value={rates.costo_por_km} onChange={(e) => setRates({ ...rates, costo_por_km: e.target.value })}/>
        <p>Entrega = {formatMoney(rates.costo_fijo_entrega || '0')} + {formatMoney(rates.costo_por_km || '0')} × distancia.</p><button type="submit">Guardar tarifas</button>
      </fieldset></form>}
      {creating && <Dialog title="Incorporar repartidor" busy={busy} onClose={() => setCreating(false)}>
        {(error || queryError) && <p role="alert" className="auth-error">{error || queryError}</p>}
        <form className="menu-form" onSubmit={(event) => {
          event.preventDefault(); const form = new FormData(event.currentTarget); const element = event.currentTarget;
          setBusy(true); setError(''); setNotice('');
          void operationRequest(path, { nombre: form.get('nombre'), correo: form.get('correo'), contrasena: form.get('contrasena'), telefono: form.get('telefono'), zona: form.get('zona') }, undefined, 'POST')
            .then(async () => { element.reset(); setCreating(false); setNotice('Repartidor incorporado. Activá su disponibilidad cuando comience a trabajar.'); })
            .catch(failed).finally(() => setBusy(false));
        }}><fieldset disabled={busy}>
          <label htmlFor="courier-name">Nombre y apellido</label><input id="courier-name" name="nombre" required maxLength={150} autoComplete="name"/>
          <label htmlFor="courier-email">Correo</label><input id="courier-email" name="correo" type="email" required maxLength={254} autoComplete="off"/>
          <label htmlFor="courier-password">Contraseña (15 a 20 caracteres)</label><input id="courier-password" name="contrasena" type="password" required minLength={15} maxLength={20} autoComplete="new-password"/>
          <label htmlFor="courier-phone">Teléfono (opcional)</label><input id="courier-phone" name="telefono" maxLength={50}/>
          <label htmlFor="courier-zone">Zona (opcional)</label><input id="courier-zone" name="zona" maxLength={150}/>
          <p>Se crea una cuenta exclusiva de este restaurante. Usá una contraseña única y compartila de forma privada con el repartidor.</p>
          <button type="submit" className="primary-button">{busy ? 'Creando…' : 'Crear cuenta de repartidor'}</button>
        </fieldset></form>
      </Dialog>}
    </>}
    {!page ? <p>Cargando repartidores…</p> : <>
      <p>{page.abierto ? 'abierto' : 'cerrado'} · {page.delivery_disponible ? 'Delivery disponible' : 'Delivery no disponible'}</p>
      {!page.repartidores.length && <p>Todavía no hay repartidores asociados a esta cuenta.</p>}
      <div className="catalog-grid">{page.repartidores.map((row) => <article className="product-card menu-form" key={row.id_repartidor}>
        <h3>{displayText(row.nombre)}</h3><p>{row.activo ? 'Cuenta activa' : 'Cuenta inactiva'}{row.zona ? ` · Zona: ${row.zona}` : ''}</p>
        <p><Status value={row.estado_disponibilidad}/></p><p>Último cambio: {row.ultimo_cambio ? formatDateTime(row.ultimo_cambio) : 'Sin cambios registrados'}</p>
        {owner && restaurant !== null && <details><summary>Ver desempeño</summary><CourierPerformance path={`restaurantes/${restaurant}/repartidores/${row.id_repartidor}/desempeno`} onSessionExpired={onSessionExpired}/></details>}
        {owner && row.activo && restaurant !== null && <AccountRecovery path={`restaurantes/${restaurant}/repartidores/${row.id_repartidor}/compromiso`}/>}
        {restaurant === null && <><label htmlFor={`courier-${row.id_repartidor}`}>Disponibilidad de {displayText(row.nombre)}</label>
        <select id={`courier-${row.id_repartidor}`} disabled={busy || !row.activo} value={selected[row.id_repartidor] ?? row.estado_disponibilidad}
          onChange={(event) => setSelected({ ...selected, [row.id_repartidor]: event.target.value })}>
          {!['Disponible', 'No disponible'].includes(row.estado_disponibilidad) && <option value={row.estado_disponibilidad}>{row.estado_disponibilidad}</option>}
          <option>Disponible</option><option>No disponible</option>
        </select>
        <button disabled={busy || !row.activo || selected[row.id_repartidor] === row.estado_disponibilidad} onClick={() => void save(row.id_repartidor)}>Guardar disponibilidad de {displayText(row.nombre)}</button></>}
      </article>)}</div>
    </>}
  </section>;
}
