import { cacheScope, invalidateMutation, ensureApiQuery, apiKey, queryClient } from '../services/queryCache';
import { useApiQuery } from '../services/useApiQuery';
import { formatDistance } from '../services/format';
import { useEffect, useState, type FormEvent } from 'react';
import { listProducts } from '../services/menu';
import { formatMoney } from '../services/menu';
import { OrderError, orderRequest, type CustomerMenu, type MenuItem, type Order, type OrderInput, type Restaurant } from '../services/orders';
import OrderListing from './OrderListing';
import WarningBadge from './WarningBadge';
import Preparation from './Preparation';
import DeliveryTracking from './DeliveryTracking';
import { Dialog, FoodPhoto, StateClock, displayText } from './ui';

type Props = { restaurant: number | null; view?: 'list' | 'create' | 'menu' | 'detail'; initialOrder?: number; onCloseDetail?: () => void; onSessionExpired: () => void };

export function CustomerProductCard({product, busy, quantity, onAdd}: {product: MenuItem; busy: boolean; quantity: number; onAdd: () => void}) {
  return <article className="product-card catalog-product"><FoodPhoto name={product.nombre} src={product.imagen_url}/>
    <h3>{product.nombre}</h3><p>{product.descripcion || 'Sin descripción disponible.'}</p><strong>{formatMoney(product.precio)}</strong>
    <button disabled={busy || quantity >= 100} onClick={onAdd}>Agregar al carrito</button>
  </article>;
}

export default function Orders({ restaurant, view = 'list', initialOrder, onCloseDetail, onSessionExpired }: Props) {
  const [refresh, setRefresh] = useState(0);
  const [detail, setDetail] = useState<Order | null>(null);
  const [detailTab, setDetailTab] = useState('detalle');
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState<Omit<OrderInput, 'detalles'>>({ correo_cliente: '', direccion_entrega: '',
    referencia_local: '', zona_entrega: '', medio_pago: 'efectivo' });

  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo conectar con el servidor.');
  }

  const catalogPath = `restaurantes/${restaurant}/productos`;
  const catalog = useApiQuery(catalogPath, (signal) => listProducts(restaurant!, signal), onSessionExpired,
    {enabled:restaurant !== null && view === 'create', interval:30_000});
  const places = useApiQuery<Restaurant[]>('restaurantes', (signal) => orderRequest('restaurantes', undefined, signal),
    onSessionExpired, {enabled:restaurant === null && view === 'menu'});
  const menuPath = `restaurantes/${selected}/menu`;
  const customerMenu = useApiQuery<CustomerMenu>(menuPath, (signal) => orderRequest(menuPath, undefined, signal),
    onSessionExpired, {enabled:!!selected && view === 'menu', interval:30_000});
  const products = (catalog.data ?? []).filter((p) => p.activo);
  const restaurants = places.data ?? [];
  const menu = customerMenu.data;
  const queryError = catalog.error?.message ?? places.error?.message ?? customerMenu.error?.message;
  useEffect(() => {
    const rows = view === 'create' ? catalog.data : undefined;
    if (!rows) return;
    setQuantities(current => {
      const unavailable = rows.filter(p => !p.disponible_stock && Number(current[p.id_producto] ?? 0) > 0);
      if (!unavailable.length) return current;
      const next = {...current};
      unavailable.forEach(p => { delete next[p.id_producto]; });
      return next;
    });
  }, [menu, catalog.data, view]);
  async function refreshData() {
    setError(''); setBusy(true);
    try {
      await invalidateMutation(`restaurantes/${restaurant}/pedidos`, cacheScope());
      if (view === 'create') await catalog.refetch({cancelRefetch:false, throwOnError:true});
      if (view === 'menu') await Promise.all([places.refetch({cancelRefetch:false, throwOnError:true}), ...(selected ? [customerMenu.refetch({cancelRefetch:false, throwOnError:true})] : [])]);
    } catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }
  async function showDetail(id: number) {
    setBusy(true); setError(''); setDetailTab('detalle');
    setDetail(queryClient.getQueryData<Order>(apiKey(`pedidos/${id}`)) ?? null);
    try { setDetail(await ensureApiQuery(`pedidos/${id}`, (signal) => orderRequest<Order>(`pedidos/${id}`, undefined, signal))); }
    catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }

  useEffect(() => { if (initialOrder) void showDetail(initialOrder); }, [initialOrder]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setNotice('');
    if (view === 'create' && products.some(p => !p.disponible_stock && Number(quantities[p.id_producto] ?? 0) > 0)) {
      setError('Quitá del pedido los productos que ya no están disponibles.'); return;
    }
    const detalles = (view === 'menu' ? menu?.productos ?? [] : products).filter((p) => Number(quantities[p.id_producto] ?? 0) > 0)
      .map((p) => ({ id_producto: p.id_producto, cantidad: Number(quantities[p.id_producto]) }));
    if (!detalles.length) { setError('Indicá la cantidad de al menos un producto.'); return; }
    setBusy(true);
    try {
      const { correo_cliente, ...delivery } = form;
      const saved = await orderRequest<Order>(`restaurantes/${view === 'menu' ? selected : restaurant}/pedidos`, {
        ...delivery, ...(view === 'menu' ? {} : { correo_cliente }), detalles,
      });
      setDetailTab('detalle'); setDetail(saved); setNotice(`Pedido #${saved.id_pedido} guardado correctamente.`);
      setQuantities({}); setRefresh((value) => value + 1);
    } catch (failure) {
      failed(failure);
      if (failure instanceof OrderError && failure.status === 409) {
        if (view === 'menu' && selected) void customerMenu.refetch({cancelRefetch:false});
        if (view === 'create') void catalog.refetch({cancelRefetch:false});
      }
    }
    finally { setBusy(false); }
  }

  return <section id="gestion-pedidos" className="menu-manager" aria-label="Pedidos">
    {view !== 'detail' && <div className="menu-heading"><h2>{view === 'create' ? 'Armá un nuevo pedido' : view === 'menu' ? 'Elegí tu restaurante' : 'Gestioná tus pedidos'}</h2>
      <button type="button" disabled={busy} onClick={() => { void refreshData(); }}>Actualizar pedidos</button></div>}
    {(error || queryError) && <p role="alert" className="auth-error">{error || queryError}</p>}
    {notice && <p role="status" className="menu-notice">{notice}</p>}
    {view === 'create' && restaurant !== null ? <form className="menu-editor menu-form order-create-form" onSubmit={(event) => void submit(event)}>
      <h3>Registrar pedido</h3>
      <p>Ingresá el correo de un cliente registrado y elegí los productos. Confirmamos la disponibilidad de entrega al guardar.</p>
      <fieldset disabled={busy}>
        <div className="form-columns">
          <div><label htmlFor="order-email">Correo del cliente</label><input id="order-email" type="email" required maxLength={254} value={form.correo_cliente} onChange={(e) => setForm({ ...form, correo_cliente: e.target.value })} /></div>
        </div>
        <label htmlFor="order-address">Dirección de entrega</label><input id="order-address" required maxLength={500} value={form.direccion_entrega} onChange={(e) => setForm({ ...form, direccion_entrega: e.target.value })} />
        <label htmlFor="order-reference">Referencia (opcional)</label><input id="order-reference" maxLength={500} value={form.referencia_local} onChange={(e) => setForm({ ...form, referencia_local: e.target.value })} />
        <label htmlFor="order-zone">Zona (opcional)</label><input id="order-zone" maxLength={150} value={form.zona_entrega} onChange={(e) => setForm({ ...form, zona_entrega: e.target.value })} />
        <label htmlFor="order-distance">Distancia de entrega (km)</label>
        <input id="order-distance" type="number" min="0" max="10" step="0.001" required value={form.distancia_km ?? ''}
          onChange={(e) => setForm({ ...form, distancia_km: e.target.value || undefined })}/>
        <label htmlFor="order-payment">Medio de pago</label><input id="order-payment" required maxLength={50} value={form.medio_pago} onChange={(e) => setForm({ ...form, medio_pago: e.target.value })} />
        <h4>Productos activos</h4>
        <div className="order-product-grid">{products.length ? products.map((product) => <div className="order-product-choice" key={product.id_producto}>
          <FoodPhoto name={product.nombre} src={product.imagen_url}/>
          <label htmlFor={`qty-${product.id_producto}`}>{product.nombre} · {formatMoney(product.precio)} · cantidad</label>
          {!product.disponible_stock && <span className="product-state product-state--unavailable">No disponible</span>}
          <input id={`qty-${product.id_producto}`} type="number" min="0" max="2147483647" step="1" disabled={!product.disponible_stock} value={quantities[product.id_producto] ?? ''} onChange={(e) => setQuantities({ ...quantities, [product.id_producto]: e.target.value })} />
        </div>) : <p>No hay productos activos cargados. Actualizá el menú después de cargarlos.</p>}</div>
        <p>El total se confirma con los precios vigentes, sin cargos de envío.</p>
        <button className="primary-button" type="submit" disabled={!products.length}>{busy ? 'Guardando…' : 'Confirmar pedido'}</button>
      </fieldset>
    </form> : view === 'menu' ? <div className="menu-editor menu-form">
      <h3>Consultar menú</h3><label htmlFor="restaurant-menu">Restaurante</label>
      <select id="restaurant-menu" disabled={busy} value={selected} onChange={(e) => { setSelected(e.target.value); setQuantities({}); setError(''); setNotice(''); }}><option value="">Elegí un restaurante</option>
        {restaurants.map((row) => <option key={row.id_restaurante} value={row.id_restaurante}>{displayText(row.nombre)}</option>)}</select>
      {menu && <><p>{menu.restaurante.delivery_disponible ? 'Delivery disponible' : 'Delivery no disponible'}</p>
        <p className="muted">Los platos sin foto propia muestran una imagen ilustrativa.</p>
        <div className="catalog-grid">{menu.productos.length ? menu.productos.map((p) => <CustomerProductCard key={p.id_producto} product={p} busy={busy} quantity={Number(quantities[p.id_producto] ?? 0)}
          onAdd={() => setQuantities({ ...quantities, [p.id_producto]: String(Number(quantities[p.id_producto] ?? 0) + 1) })}/>) : <p>No hay productos activos.</p>}</div>
        <form className="menu-form customer-cart" onSubmit={(event) => void submit(event)}><h3>Tu carrito</h3><fieldset disabled={busy}>
          {menu.productos.filter((p) => Number(quantities[p.id_producto] ?? 0) > 0).map((p) => <div className="cart-row" key={p.id_producto}>
            <label htmlFor={`cart-${p.id_producto}`}>{p.nombre} · {formatMoney(p.precio)}</label><input id={`cart-${p.id_producto}`} type="number" min="0" max="100" step="1" required value={quantities[p.id_producto]} onChange={(e) => setQuantities({ ...quantities, [p.id_producto]: e.target.value })}/>
            <button type="button" onClick={() => setQuantities({ ...quantities, [p.id_producto]: '0' })}>Quitar</button>
          </div>)}
          <p className="order-total">Productos: {formatMoney(String(menu.productos.reduce((total, p) => total + Math.round(Number(p.precio) * 100) * Number(quantities[p.id_producto] ?? 0), 0) / 100))}</p>
          <p>Sin cargos de envío al cliente. El total se confirma con los precios vigentes.</p>
          <label htmlFor="customer-address">Dirección de entrega</label><input id="customer-address" required maxLength={500} value={form.direccion_entrega} onChange={(e) => setForm({ ...form, direccion_entrega: e.target.value })}/>
          <label htmlFor="customer-reference">Referencia (opcional)</label><input id="customer-reference" maxLength={500} value={form.referencia_local} onChange={(e) => setForm({ ...form, referencia_local: e.target.value })}/>
          <label htmlFor="customer-payment">Medio de pago</label><select id="customer-payment" value={form.medio_pago} onChange={(e) => setForm({ ...form, medio_pago: e.target.value })}><option value="efectivo">Efectivo</option><option value="transferencia">Transferencia</option></select>
          <label htmlFor="customer-distance">Distancia de entrega (km)</label>
          <input id="customer-distance" type="number" min="0" max="10" step="0.001" required value={form.distancia_km ?? ''}
            onChange={(e) => setForm({ ...form, distancia_km: e.target.value || undefined })}/>
          <p className="muted">La cobertura de entrega es de hasta 10 km.</p>
          <button className="primary-button" type="submit" disabled={!menu.restaurante.delivery_disponible || !menu.productos.some((p) => Number(quantities[p.id_producto] ?? 0) > 0)}>{busy ? 'Confirmando…' : 'Confirmar pedido'}</button>
          {!menu.restaurante.delivery_disponible && <p>Podés explorar el menú. El restaurante está cerrado y no recibe pedidos.</p>}
        </fieldset></form></>}
    </div> : null}
    {view === 'list' && <OrderListing key={restaurant ?? 'cliente'} restaurant={restaurant} refresh={refresh}
      onOpen={(id) => void showDetail(id)} onSessionExpired={onSessionExpired}/>}
    {detail && <Dialog title={`Pedido #${detail.id_pedido}`} onClose={() => { setDetail(null); setRefresh((n) => n + 1); onCloseDetail?.(); }}>
      <div className="tabs" role="tablist" aria-label="Secciones del pedido">
        {['detalle', ...(restaurant !== null ? ['preparacion'] : []), 'seguimiento'].map((tab) => <button type="button" role="tab" aria-selected={detailTab === tab} key={tab} onClick={() => setDetailTab(tab)}>{tab === 'detalle' ? 'Detalle' : tab === 'preparacion' ? 'Preparación' : 'Seguimiento'}</button>)}
      </div>
      {detailTab === 'detalle' && <article className="order-detail" aria-label={`Detalle del pedido ${detail.id_pedido}`}>
      <h3>Detalle del pedido #{detail.id_pedido}<WarningBadge message={detail.advertencia_importe}/></h3><p>Cliente: {displayText(detail.cliente)}</p><p>Estado: {detail.estado}</p>
      <StateClock since={detail.estado_desde} state={detail.estado}/>
      {detail.preparacion_minutos !== null && <p>Tiempo de preparación: {Number(detail.preparacion_minutos).toFixed(2)} min</p>}
      {detail.entrega_minutos !== null && <p>Tiempo de entrega: {Number(detail.entrega_minutos).toFixed(2)} min</p>}
      <p>Entrega: {detail.direccion_entrega}</p>{detail.referencia_local && <p>Referencia: {detail.referencia_local}</p>}
      {detail.zona_entrega && <p>Zona: {detail.zona_entrega}</p>}<p>Distancia: {detail.distancia_km === null ? 'Sin confirmar' : `${formatDistance(detail.distancia_km)} km registrados`}</p>
      <p>Pago: {detail.medio_pago} · {detail.estado_pago}</p>
      <ul>{detail.detalles.map((row) => <li key={row.id_producto}>{displayText(row.nombre)} × {row.cantidad} · {formatMoney(row.precio_unitario)} c/u · {formatMoney(row.subtotal)}</li>)}</ul>
      <p className="order-total">Total: {formatMoney(detail.importe_total)}</p>
      {detail.economia && detail.distancia_km !== null && <section className="economy-summary"><h3>Resultado económico estimado</h3>
        <dl><dt>Importe de productos</dt><dd>{formatMoney(detail.economia.importe_productos)}</dd><dt>Costo estimado de productos</dt><dd>{formatMoney(detail.economia.costo_productos)}</dd>
          <dt>Entrega fija</dt><dd>{formatMoney(detail.economia.costo_fijo_entrega)}</dd><dt>Por kilómetro</dt><dd>{formatMoney(detail.economia.costo_por_km)} × {formatDistance(detail.distancia_km)} km = {formatMoney(detail.economia.componente_km)}</dd>
          <dt>Costo de entrega</dt><dd>{formatMoney(detail.economia.costo_entrega)}</dd><dt>Margen estimado</dt><dd>{formatMoney(detail.economia.margen_estimado)}</dd></dl>
        <p className="muted">Estimación operativa con tarifas vigentes; no es una liquidación contable.</p>
        {detail.economia.costo_entrega_asignado && <p>Costo de reparto guardado al asignar: {formatMoney(detail.economia.costo_entrega_asignado)}</p>}
      </section>}</article>}
      {detailTab === 'seguimiento' && <DeliveryTracking key={`tracking-${detail.id_pedido}`} order={detail.id_pedido} manage={false}
        onUpdated={() => { setRefresh((n) => n + 1); void ensureApiQuery(`pedidos/${detail.id_pedido}`, (signal) => orderRequest<Order>(`pedidos/${detail.id_pedido}`, undefined, signal)).then(setDetail).catch(failed); }} onSessionExpired={onSessionExpired} />}
      {detailTab === 'preparacion' && restaurant !== null && <Preparation key={detail.id_pedido} restaurant={restaurant} order={detail.id_pedido}
        onSessionExpired={onSessionExpired} onChanged={() => {
          void ensureApiQuery(`pedidos/${detail.id_pedido}`, (signal) => orderRequest<Order>(`pedidos/${detail.id_pedido}`, undefined, signal)).then((updated) => {
            setDetail((current) => current?.id_pedido === updated.id_pedido ? updated : current);
            setRefresh((value) => value + 1);
          }).catch(failed);
        }} />}
    </Dialog>}
  </section>;
}
