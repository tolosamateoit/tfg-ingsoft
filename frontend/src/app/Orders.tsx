import { useEffect, useState, type FormEvent } from 'react';
import { listProducts } from '../services/menu';
import { formatMoney } from '../services/menu';
import { OrderError, orderRequest, type CustomerMenu, type MenuItem, type Order, type OrderInput, type OrderPage, type Restaurant } from '../services/orders';
import Preparation from './Preparation';
import DeliveryTracking from './DeliveryTracking';
import { Dialog, FoodPhoto, Status, displayText } from './ui';

type Props = { restaurant: number | null; view?: 'list' | 'create' | 'menu'; onSessionExpired: () => void };

export default function Orders({ restaurant, view = 'list', onSessionExpired }: Props) {
  const [page, setPage] = useState<OrderPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [detail, setDetail] = useState<Order | null>(null);
  const [detailTab, setDetailTab] = useState('detalle');
  const [products, setProducts] = useState<MenuItem[]>([]);
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [menu, setMenu] = useState<CustomerMenu | null>(null);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState<Omit<OrderInput, 'detalles'>>({ correo_cliente: '', direccion_entrega: '',
    referencia_local: '', zona_entrega: '', medio_pago: 'efectivo', distancia_km: '' });

  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo conectar con el servidor.');
  }

  useEffect(() => {
    if (view !== 'list') { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    void orderRequest<OrderPage>(`pedidos?limit=20&offset=${offset}`, undefined, controller.signal)
      .then(setPage).catch((failure: unknown) => { if (!controller.signal.aborted) failed(failure); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [offset, refresh, view]);

  useEffect(() => {
    const controller = new AbortController();
    if (restaurant !== null) {
      void listProducts(restaurant, controller.signal).then((rows) => setProducts(rows.filter((p) => p.activo)))
        .catch((failure: unknown) => { if (!controller.signal.aborted) failed(failure); });
    } else {
      void orderRequest<Restaurant[]>('restaurantes', undefined, controller.signal).then(setRestaurants)
        .catch((failure: unknown) => { if (!controller.signal.aborted) failed(failure); });
    }
    return () => controller.abort();
  }, [restaurant, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    setMenu(null);
    if (selected) void orderRequest<CustomerMenu>(`restaurantes/${selected}/menu`, undefined, controller.signal)
      .then(setMenu).catch((failure: unknown) => { if (!controller.signal.aborted) failed(failure); });
    return () => controller.abort();
  }, [selected, refresh]);

  async function showDetail(id: number) {
    setBusy(true); setError(''); setDetailTab('detalle');
    try { setDetail(await orderRequest<Order>(`pedidos/${id}`)); }
    catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setNotice('');
    const detalles = products.filter((p) => Number(quantities[p.id_producto] ?? 0) > 0)
      .map((p) => ({ id_producto: p.id_producto, cantidad: Number(quantities[p.id_producto]) }));
    if (!detalles.length) { setError('Indicá la cantidad de al menos un producto.'); return; }
    setBusy(true);
    try {
      const saved = await orderRequest<Order>(`restaurantes/${restaurant}/pedidos`, { ...form, detalles });
      setDetailTab('detalle'); setDetail(saved); setNotice(`Pedido #${saved.id_pedido} guardado correctamente.`);
      setQuantities({}); setOffset(0); setRefresh((value) => value + 1);
    } catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }

  return <section id="gestion-pedidos" className="menu-manager" aria-label="Pedidos">
    <div className="menu-heading"><h2>{view === 'create' ? 'Armá un nuevo pedido' : view === 'menu' ? 'Elegí tu restaurante' : 'Todos los pedidos'}</h2>
      <button type="button" disabled={busy || loading} onClick={() => { setError(''); setRefresh((value) => value + 1); }}>Actualizar pedidos y menú</button></div>
    {error && <p role="alert" className="auth-error">{error}</p>}
    {notice && <p role="status" className="menu-notice">{notice}</p>}
    {view === 'create' && restaurant !== null ? <form className="menu-editor menu-form order-create-form" onSubmit={(event) => void submit(event)}>
      <h3>Registrar pedido</h3>
      <p>Ingresá el correo de un cliente registrado y elegí los productos. Confirmamos la disponibilidad de entrega al guardar.</p>
      <fieldset disabled={busy}>
        <div className="form-columns">
          <div><label htmlFor="order-email">Correo del cliente</label><input id="order-email" type="email" required maxLength={254} value={form.correo_cliente} onChange={(e) => setForm({ ...form, correo_cliente: e.target.value })} /></div>
          <div><label htmlFor="order-distance">Distancia estimada (km)</label><input id="order-distance" type="number" required min="0" max="999999999.999" step="0.001" value={form.distancia_km} onChange={(e) => setForm({ ...form, distancia_km: e.target.value })} /></div>
        </div>
        <label htmlFor="order-address">Dirección de entrega</label><input id="order-address" required maxLength={500} value={form.direccion_entrega} onChange={(e) => setForm({ ...form, direccion_entrega: e.target.value })} />
        <label htmlFor="order-reference">Referencia (opcional)</label><input id="order-reference" maxLength={500} value={form.referencia_local} onChange={(e) => setForm({ ...form, referencia_local: e.target.value })} />
        <label htmlFor="order-zone">Zona (opcional)</label><input id="order-zone" maxLength={150} value={form.zona_entrega} onChange={(e) => setForm({ ...form, zona_entrega: e.target.value })} />
        <label htmlFor="order-payment">Medio de pago</label><input id="order-payment" required maxLength={50} value={form.medio_pago} onChange={(e) => setForm({ ...form, medio_pago: e.target.value })} />
        <h4>Productos activos</h4>
        <div className="order-product-grid">{products.length ? products.map((product) => <div className="order-product-choice" key={product.id_producto}>
          <FoodPhoto name={product.nombre}/>
          <label htmlFor={`qty-${product.id_producto}`}>{product.nombre} · {formatMoney(product.precio)} · cantidad</label>
          <input id={`qty-${product.id_producto}`} type="number" min="0" max="2147483647" step="1" value={quantities[product.id_producto] ?? ''} onChange={(e) => setQuantities({ ...quantities, [product.id_producto]: e.target.value })} />
        </div>) : <p>No hay productos activos cargados. Actualizá el menú después de cargarlos.</p>}</div>
        <p>El total se confirma con los precios vigentes, sin cargos de envío.</p>
        <button className="primary-button" type="submit" disabled={!products.length}>{busy ? 'Guardando…' : 'Confirmar pedido'}</button>
      </fieldset>
    </form> : view === 'menu' ? <div className="menu-editor menu-form">
      <h3>Consultar menú</h3><label htmlFor="restaurant-menu">Restaurante</label>
      <select id="restaurant-menu" value={selected} onChange={(e) => setSelected(e.target.value)}><option value="">Elegí un restaurante</option>
        {restaurants.map((row) => <option key={row.id_restaurante} value={row.id_restaurante}>{displayText(row.nombre)}</option>)}</select>
      {menu && <><p>{menu.restaurante.delivery_disponible ? 'Delivery disponible' : 'Delivery no disponible'}</p>
        <div className="catalog-grid">{menu.productos.length ? menu.productos.map((p) => <article className="product-card catalog-product" key={p.id_producto}><FoodPhoto name={p.nombre}/><h3>{p.nombre}</h3><strong>{formatMoney(p.precio)}</strong></article>) : <p>No hay productos activos.</p>}</div></>}
      <p>El personal del restaurante registra el pedido y su distancia estimada.</p>
    </div> : null}
    {view === 'list' && <>
    {loading && <p role="status">Cargando pedidos…</p>}
    {!loading && page && <>
      {!page.pedidos.length && <p>No hay pedidos registrados.</p>}
      <div className="catalog-grid">{page.pedidos.map((row) => <article className="product-card" key={row.id_pedido}>
        <div className="product-title"><h3>Pedido #{row.id_pedido}</h3><Status value={row.estado}/></div><p>{displayText(row.restaurante)} · {displayText(row.cliente)}</p>
        <p className="muted">{new Date(row.fecha_hora).toLocaleString('es-AR')}</p><p className="order-total">{formatMoney(row.importe_total)}</p>
        <button disabled={busy} onClick={() => void showDetail(row.id_pedido)}>Ver pedido #{row.id_pedido}</button>
      </article>)}</div>
      <div className="menu-actions"><button disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Anteriores</button>
        <button disabled={busy || offset + 20 >= page.total} onClick={() => setOffset(offset + 20)}>Siguientes</button></div>
    </>}
    </>}
    {detail && <Dialog title={`Pedido #${detail.id_pedido}`} onClose={() => setDetail(null)}>
      <div className="tabs" role="tablist" aria-label="Secciones del pedido">
        {['detalle', ...(restaurant !== null ? ['preparacion'] : []), 'seguimiento'].map((tab) => <button type="button" role="tab" aria-selected={detailTab === tab} key={tab} onClick={() => setDetailTab(tab)}>{tab === 'detalle' ? 'Detalle' : tab === 'preparacion' ? 'Preparación' : 'Seguimiento'}</button>)}
      </div>
      {detailTab === 'detalle' && <article className="order-detail" aria-label={`Detalle del pedido ${detail.id_pedido}`}>
      <h3>Detalle del pedido #{detail.id_pedido}</h3><p>Cliente: {displayText(detail.cliente)}</p><p>Estado: {detail.estado}</p>
      <p>Entrega: {detail.direccion_entrega}</p>{detail.referencia_local && <p>Referencia: {detail.referencia_local}</p>}
      {detail.zona_entrega && <p>Zona: {detail.zona_entrega}</p>}<p>Distancia estimada: {detail.distancia_km} km</p>
      <p>Pago: {detail.medio_pago} · {detail.estado_pago}</p>
      <ul>{detail.detalles.map((row) => <li key={row.id_producto}>{displayText(row.nombre)} × {row.cantidad} · {formatMoney(row.precio_unitario)} c/u · {formatMoney(row.subtotal)}</li>)}</ul>
      <p className="order-total">Total: {formatMoney(detail.importe_total)}</p></article>}
      {detailTab === 'seguimiento' && <DeliveryTracking key={`tracking-${detail.id_pedido}`} order={detail.id_pedido} onSessionExpired={onSessionExpired} />}
      {detailTab === 'preparacion' && restaurant !== null && <Preparation key={detail.id_pedido} restaurant={restaurant} order={detail.id_pedido}
        onSessionExpired={onSessionExpired} onChanged={(estado) => {
          setDetail((current) => current && current.id_pedido === detail.id_pedido ? { ...current, estado } : current);
          setPage((current) => current ? { ...current, pedidos: current.pedidos.map((row) => row.id_pedido === detail.id_pedido ? { ...row, estado } : row) } : current);
        }} />}
    </Dialog>}
  </section>;
}
