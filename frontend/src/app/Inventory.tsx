import { useApiQuery } from '../services/useApiQuery';
import { formatDateTime } from '../services/format';
import { useState, type FormEvent } from 'react';
import { operationRequest } from '../services/operations';
import { OrderError } from '../services/orders';
import { formatMoney } from '../services/menu';
import { Dialog } from './ui';
import Orders from './Orders';

type Ingredient = { id_insumo: number; nombre: string; unidad: string; stock_actual: string; costo_unitario: string };
type Movement = { id_movimiento: number; nombre: string; unidad: string; id_pedido: number | null; fecha_hora: string; tipo: string; cantidad: string; motivo: string | null };
type Props = { restaurant: number; onSessionExpired: () => void };

export default function Inventory({ restaurant, onSessionExpired }: Props) {
  const [offset, setOffset] = useState(0);
  const [editor, setEditor] = useState<Ingredient | 'new' | null>(null);
  const [moving, setMoving] = useState<Ingredient | null>(null);
  const [order, setOrder] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const base = `restaurantes/${restaurant}`;
  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo consultar el inventario.');
  }
  const supplies = useApiQuery<Ingredient[]>(`${base}/insumos`,
    (signal) => operationRequest(`${base}/insumos`, undefined, signal), onSessionExpired);
  const historyPath = `${base}/movimientos-stock?offset=${offset}`;
  const history = useApiQuery<Movement[]>(historyPath,
    (signal) => operationRequest(historyPath, undefined, signal), onSessionExpired);
  const rows = supplies.data ?? [];
  const movements = history.data ?? [];
  const loaded = !!supplies.data && !!history.data;
  const queryError = supplies.error?.message ?? history.error?.message;
  async function load() {
    await Promise.all([supplies.refetch({cancelRefetch:false,throwOnError:true}), history.refetch({cancelRefetch:false,throwOnError:true})]);
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    setBusy(true); setError(''); setNotice('');
    try {
      if (moving) await operationRequest(`${base}/insumos/${moving.id_insumo}/movimientos`, {
        tipo: form.get('tipo') === 'restar' ? 'ajuste' : 'reposicion', cantidad: String(Number(form.get('cantidad')) * (form.get('tipo') === 'restar' ? -1 : 1)), motivo: form.get('motivo'),
      }, undefined, 'POST');
      else await operationRequest(`${base}/insumos${editor !== 'new' && editor ? `/${editor.id_insumo}` : ''}`, {
        nombre: form.get('nombre'), unidad: form.get('unidad'), costo_unitario: form.get('costo'),
      }, undefined, editor === 'new' ? 'POST' : 'PUT');
      setEditor(null); setMoving(null); setNotice('Inventario actualizado.');
    } catch (failure) { failed(failure); } finally { setBusy(false); }
  }
  return <section className="menu-manager" aria-label="Insumos y stock">
    <div className="menu-heading"><h2>Existencias de tu cocina</h2><div className="menu-actions">
      <button className="primary-button" disabled={busy} onClick={() => { setError(''); setEditor('new'); }}>Nuevo insumo</button>
      <button disabled={busy} onClick={() => { setError(''); void load().catch(failed); }}>Actualizar stock</button>
    </div></div>
    {(error || queryError) && <p role="alert" className="auth-error">{error || queryError}</p>}{notice && <p role="status" className="menu-notice">{notice}</p>}
    {!loaded && !error && <p>Cargando inventario…</p>}
    {loaded && !rows.length && <p>Todavía no hay insumos registrados.</p>}
    <div className="catalog-grid">{rows.map((row) => <article className="product-card" key={row.id_insumo}>
      <h3>{row.nombre}</h3><p className={Number(row.stock_actual) < 0 ? 'auth-error' : 'order-total'}>{Number(row.stock_actual).toLocaleString('es-AR', { maximumFractionDigits: 6 })} {row.unidad}</p>
      <p>Costo por {row.unidad}: {formatMoney(row.costo_unitario)}</p><div className="menu-actions">
        <button onClick={() => { setError(''); setEditor(row); }}>Editar insumo</button><button onClick={() => { setError(''); setMoving(row); }}>Registrar movimiento</button>
      </div></article>)}</div>
    <h2>Movimientos de stock</h2><p>Reposiciones, ajustes y consumos automáticos de preparación. Un ajuste indica la diferencia que se suma o resta al stock.</p>
    <div className="stock-history">{movements.map((row) => <article className="product-card" key={row.id_movimiento}>
      <h3>{row.nombre} · {({ reposicion: 'Reposición', ajuste: 'Ajuste', consumo: 'Consumo' } as Record<string, string>)[row.tipo] ?? row.tipo}</h3><p>{Number(row.cantidad).toLocaleString('es-AR', { maximumFractionDigits: 6 })} {row.unidad} · {formatDateTime(row.fecha_hora)}</p><p>{row.motivo}</p>
      {row.id_pedido !== null && <button onClick={() => setOrder(row.id_pedido)}>Ver pedido #{row.id_pedido}</button>}
    </article>)}</div>
    {loaded && !movements.length && <p>No hay movimientos en esta página.</p>}
    <div className="menu-actions"><button disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - 30))}>Anteriores</button><button disabled={movements.length < 30 || busy} onClick={() => setOffset(offset + 30)}>Siguientes</button></div>
    {(editor || moving) && <Dialog title={moving ? `Movimiento de ${moving.nombre}` : editor === 'new' ? 'Nuevo insumo' : 'Editar insumo'} busy={busy} onClose={() => { setEditor(null); setMoving(null); }}>
      {(error || queryError) && <p role="alert" className="auth-error">{error || queryError}</p>}
      <form className="menu-form" onSubmit={(event) => void save(event)}><fieldset disabled={busy}>
        {moving ? <><label htmlFor="stock-type">Tipo</label><select id="stock-type" name="tipo"><option value="reposicion">Agregar stock (+)</option><option value="restar">Restar stock (−)</option></select>
          <label htmlFor="stock-qty">Cantidad a sumar o restar ({moving.unidad})</label><input id="stock-qty" name="cantidad" type="number" min="0.000001" step="0.000001" required />
          <label htmlFor="stock-reason">Motivo (opcional)</label><input id="stock-reason" name="motivo" maxLength={500} />
        </> : <><label htmlFor="stock-name">Nombre</label><input id="stock-name" name="nombre" required maxLength={150} defaultValue={editor && editor !== 'new' ? editor.nombre : ''}/>
          <label htmlFor="stock-unit">Unidad de medida</label><select id="stock-unit" name="unidad" required defaultValue={editor && editor !== 'new' ? editor.unidad : 'unidad'}><option value="unidad">Unidad</option><option value="kg">Kilogramo</option><option value="l">Litro</option></select>
          <label htmlFor="stock-cost">Costo unitario</label><input id="stock-cost" name="costo" type="number" min="0" step="0.01" required defaultValue={editor && editor !== 'new' ? editor.costo_unitario : '0'}/>
          <p>El stock inicial es cero. Registrá una reposición para cargar existencias.</p></>}
        <button className="primary-button" type="submit">{busy ? 'Guardando…' : 'Guardar'}</button>
      </fieldset></form>
    </Dialog>}
    {order !== null && <Orders restaurant={restaurant} view="detail" initialOrder={order} onCloseDetail={() => setOrder(null)} onSessionExpired={onSessionExpired}/>}
  </section>;
}
