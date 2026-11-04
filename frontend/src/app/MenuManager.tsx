import { apiKey, cacheScope, queryClient, ensureApiQuery } from '../services/queryCache';
import { useApiQuery } from '../services/useApiQuery';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Dialog, FoodPhoto, Icon } from './ui';
import {
  MenuError, createProduct, formatMoney, getRecipe, listIngredients, listProducts,
  saveRecipe, updateProduct, type Ingredient, type Product, type ProductInput, type RecipeItem,
} from '../services/menu';

type Props = { restaurant: number; onSessionExpired: () => void };
type Editor = { kind: 'product'; product?: Product } | { kind: 'recipe'; product: Product };

function errorMessage(error: unknown) {
  return error instanceof MenuError ? error.message : 'No se pudo confirmar la operación. Comprobá la conexión y volvé a cargar los datos.';
}

function ProductForm({ product, busy, onSave, onCancel }: {
  product?: Product; busy: boolean; onSave: (data: ProductInput) => void; onCancel: () => void;
}) {
  const [draft, setDraft] = useState<ProductInput>({ nombre: product?.nombre ?? '', precio: product?.precio ?? '',
    costo_unitario: product?.costo_unitario ?? '0', activo: product?.activo ?? true,
    descripcion: product?.descripcion ?? '', imagen_url: product?.imagen_url ?? '' });
  function submit(event: FormEvent) { event.preventDefault(); onSave(draft); }
  return (
    <form className="menu-form" onSubmit={submit} aria-label={product ? 'Editar producto' : 'Nuevo producto'}>
      <h3>{product ? `Editar ${product.nombre}` : 'Nuevo producto'}</h3>
      <fieldset disabled={busy}>
        <label htmlFor="product-name">Nombre</label>
        <input id="product-name" required maxLength={150} value={draft.nombre}
          onChange={(event) => setDraft({ ...draft, nombre: event.target.value })} />
        <div className="form-columns">
          <div><label htmlFor="product-price">Precio de venta ($)</label>
            <input id="product-price" type="number" min="0" step="0.01" required value={draft.precio}
              onChange={(event) => setDraft({ ...draft, precio: event.target.value })} /></div>
          <div><label htmlFor="product-cost">Costo unitario ($)</label>
            <input id="product-cost" readOnly title="Se calcula al guardar la receta o equivalencia del producto envasado" type="number" min="0" step="0.01" required value={draft.costo_unitario}
              onChange={(event) => setDraft({ ...draft, costo_unitario: event.target.value })} /></div>
        </div>
        <p className="muted">El costo se calcula con los insumos de la receta. Para envasados, registrá su equivalencia (por ejemplo, una botella por unidad).</p>
        <label htmlFor="product-description">Descripción (opcional)</label><textarea id="product-description" maxLength={1000} value={draft.descripcion ?? ''} onChange={(event) => setDraft({ ...draft, descripcion: event.target.value })}/>
        <label htmlFor="product-image">URL de imagen (opcional)</label><input id="product-image" maxLength={2000} value={draft.imagen_url ?? ''} placeholder="https://… o /images/…" onChange={(event) => setDraft({ ...draft, imagen_url: event.target.value })}/>
        <label className="checkbox-label"><input type="checkbox" checked={draft.activo}
          onChange={(event) => setDraft({ ...draft, activo: event.target.checked })} />Activo en el menú</label>
        <div className="menu-actions">
          <button type="submit">{busy ? 'Guardando…' : 'Guardar producto'}</button>
          <button type="button" onClick={onCancel}>Cancelar</button>
        </div>
      </fieldset>
    </form>
  );
}

function RecipeEditor({ restaurant, product, ingredients, onCancel, onSessionExpired, onBusyChange }: {
  restaurant: number; product: Product; ingredients: Ingredient[]; onCancel: () => void; onSessionExpired: () => void; onBusyChange: (busy: boolean) => void;
}) {
  const path = `restaurantes/${restaurant}/productos/${product.id_producto}/receta`;
  const cached = queryClient.getQueryData<import('../services/menu').Recipe>(apiKey(path));
  const [rows, setRows] = useState<(RecipeItem & { key: number })[]>(() => cached?.detalles.map((item,key) => ({...item,key})) ?? []);
  const [loading, setLoading] = useState(!cached);
  const [loaded, setLoaded] = useState(!!cached);
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const nextKey = useRef(rows.length);
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(!queryClient.getQueryData(apiKey(path))); setError('');
    void ensureApiQuery(path, (signal) => getRecipe(restaurant, product.id_producto, signal)).then((recipe) => {
      if (!controller.signal.aborted) { setRows(recipe.detalles.map((item) => ({ ...item, key: nextKey.current++ }))); setLoaded(true); }
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) {
        setError(errorMessage(failure));
        if (failure instanceof MenuError && failure.status === 401) onSessionExpired();
      }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [restaurant, product.id_producto, onSessionExpired, retry]);

  function addIngredient() {
    const available = ingredients.find((item) => !rows.some((row) => row.id_insumo === item.id_insumo));
    if (available) setRows([...rows, { key: nextKey.current++, id_insumo: available.id_insumo, cantidad: '1', unidad: available.unidad }]);
    setNotice('');
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(''); setNotice('');
    const key = apiKey(path);
    try {
      const recipe = await saveRecipe(restaurant, product.id_producto, rows.map(({ id_insumo, cantidad, unidad }) => ({ id_insumo, cantidad, unidad })));
      if (key[0] === cacheScope()) queryClient.setQueryData(key, recipe);
      setRows(recipe.detalles.map((item) => ({ ...item, key: nextKey.current++ })));
      setNotice('Receta guardada.');
    } catch (failure) {
      setError(errorMessage(failure));
      if (failure instanceof MenuError && failure.status === 401) onSessionExpired();
    } finally { setBusy(false); }
  }

  return (
    <form className="menu-form" onSubmit={(event) => void submit(event)} aria-label="Editar receta" aria-busy={loading || busy}>
      <h3>Receta de {product.nombre}</h3>
      <p>Indicá las cantidades necesarias para una unidad del producto, en la unidad registrada de cada insumo.</p>
      {loading ? <p role="status">Cargando receta…</p> : loaded && (
        <fieldset disabled={busy}>
          {ingredients.length === 0 && <p>Todavía no hay insumos registrados para este restaurante.</p>}
          {rows.length === 0 && <p>Esta receta no contiene insumos.</p>}
          {rows.map((row, index) => (
            <div className="recipe-row" key={row.key}>
              <div><label htmlFor={`ingredient-${row.key}`}>Insumo {index + 1}</label>
                <select id={`ingredient-${row.key}`} value={row.id_insumo} onChange={(event) => {
                  const ingredient = ingredients.find((item) => item.id_insumo === Number(event.target.value));
                  if (ingredient) setRows(rows.map((item) => item.key === row.key
                    ? { ...item, id_insumo: ingredient.id_insumo, unidad: ingredient.unidad } : item));
                  setNotice('');
                }}>
                  {ingredients.filter((item) => item.id_insumo === row.id_insumo || !rows.some((other) => other.id_insumo === item.id_insumo))
                    .map((item) => <option key={item.id_insumo} value={item.id_insumo}>{item.nombre}</option>)}
                </select></div>
              <div><label htmlFor={`quantity-${row.key}`}>Cantidad {index + 1}</label>
                <input id={`quantity-${row.key}`} type="number" min="0.000001" step="0.000001" required value={row.cantidad}
                  onChange={(event) => { setRows(rows.map((item) => item.key === row.key ? { ...item, cantidad: event.target.value } : item)); setNotice(''); }} /></div>
              <div><label htmlFor={`unit-${row.key}`}>Unidad {index + 1}</label><input id={`unit-${row.key}`} readOnly value={row.unidad} /></div>
              <button type="button" aria-label={`Quitar insumo ${index + 1}`} onClick={() => { setRows(rows.filter((item) => item.key !== row.key)); setNotice(''); }}>Quitar</button>
            </div>
          ))}
          <button type="button" disabled={rows.length >= ingredients.length || rows.length >= 100} onClick={addIngredient}>Agregar insumo</button>
          <div className="menu-actions">
            <button type="submit">{busy ? 'Guardando…' : 'Guardar receta'}</button>
            <button type="button" onClick={onCancel}>Cerrar receta</button>
          </div>
        </fieldset>
      )}
      {!loading && error && <p className="auth-error" role="alert">{error}</p>}
      {notice && <p className="menu-notice" role="status">{notice}</p>}
      {!loading && !loaded && <button type="button" onClick={() => setRetry(retry + 1)}>Volver a cargar receta</button>}
      {(loading || !loaded) && <button type="button" onClick={onCancel}>Cerrar receta</button>}
    </form>
  );
}

export default function MenuManager({ restaurant, onSessionExpired }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editor, setEditor] = useState<Editor | null>(null);

  const catalog = useApiQuery(`restaurantes/${restaurant}/productos`, (signal) => listProducts(restaurant, signal), onSessionExpired);
  const supplies = useApiQuery(`restaurantes/${restaurant}/insumos`, (signal) => listIngredients(restaurant, signal), onSessionExpired);
  const products = catalog.data ?? [];
  const ingredients = supplies.data ?? [];
  const loading = catalog.isPending || supplies.isPending;
  const queryError = catalog.error?.message ?? supplies.error?.message;
  async function reload() { await Promise.all([catalog.refetch({cancelRefetch:false}), supplies.refetch({cancelRefetch:false})]); }

  async function saveProduct(data: ProductInput) {
    if (editor?.kind !== 'product') return;
    setBusy(true); setError(''); setNotice('');
    try {
      editor.product ? await updateProduct(restaurant, editor.product.id_producto, data) : await createProduct(restaurant, data);
      setEditor(null); setNotice('Producto guardado.');
    } catch (failure) {
      setError(errorMessage(failure));
      if (failure instanceof MenuError && failure.status === 401) onSessionExpired();
    } finally { setBusy(false); }
  }

  return (
    <section className="menu-manager" aria-labelledby="menu-title">
      <div className="menu-heading"><div><h2 id="menu-title">Tu carta</h2><p>Productos que salen de tu cocina. Imágenes ilustrativas.</p></div>
        <div className="menu-actions">
          <button className="primary-button" type="button" disabled={loading || editor !== null} onClick={() => { setNotice(''); setError(''); setEditor({ kind: 'product' }); }}><Icon name="plus" size={17}/>Nuevo producto</button>
          <button type="button" disabled={loading || editor !== null} onClick={() => { setNotice(''); void reload(); }}>Actualizar catálogo</button>
        </div>
      </div>
      {loading && <p role="status">Cargando catálogo…</p>}
      {(error || queryError) && !editor && <p className="auth-error" role="alert">{error || queryError}</p>}
      {notice && <p className="menu-notice" role="status">{notice}</p>}
      {!loading && !error && products.length === 0 && <p>Todavía no hay productos. Creá el primero para comenzar.</p>}
      <div className="catalog-grid">
        {products.map((product) => <article className="product-card catalog-product" key={product.id_producto}>
          <FoodPhoto name={product.nombre} src={product.imagen_url}/>
          {product.descripcion && <p>{product.descripcion}</p>}
          <div className="product-title"><h3>{product.nombre}</h3><span className={`product-state ${product.activo ? 'product-state--active' : ''}`}>{product.activo ? 'Activo' : 'Inactivo'}</span></div>
          <dl><dt>Precio de venta</dt><dd>{formatMoney(product.precio)}</dd><dt>Costo unitario</dt><dd>{formatMoney(product.costo_unitario)}</dd></dl>
          <div className="menu-actions">
            <button type="button" disabled={editor !== null || loading} aria-label={`Editar ${product.nombre}`} onClick={() => { setNotice(''); setError(''); setEditor({ kind: 'product', product }); }}>Editar</button>
            <button type="button" disabled={editor !== null || loading} aria-label={`Receta de ${product.nombre}`} onClick={() => { setNotice(''); setError(''); setEditor({ kind: 'recipe', product }); }}>Receta</button>
          </div>
        </article>)}
      </div>
      {editor && <Dialog title={editor.kind === 'product' ? (editor.product ? 'Editar producto' : 'Nuevo producto') : `Receta de ${editor.product.nombre}`} busy={busy} onClose={() => { setEditor(null); setError(''); }}>
        {error && <p className="auth-error" role="alert">{error}</p>}
        {editor.kind === 'product'
          ? <ProductForm key={editor.product?.id_producto ?? 'new'} product={editor.product} busy={busy}
            onSave={(data) => void saveProduct(data)} onCancel={() => { setEditor(null); setError(''); }} />
          : <RecipeEditor key={editor.product.id_producto} restaurant={restaurant} product={editor.product} ingredients={ingredients}
            onCancel={() => setEditor(null)} onSessionExpired={onSessionExpired} onBusyChange={setBusy} />}
      </Dialog>}
    </section>
  );
}
