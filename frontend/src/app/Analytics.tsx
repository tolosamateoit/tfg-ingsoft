import { useEffect, useState } from 'react';
import { operationRequest } from '../services/operations';
import { OrderError } from '../services/orders';
import type { Alert, Forecast, Metrics } from '../services/analytics';

type Props = { restaurant: number; view?: 'forecast' | 'metrics'; onSessionExpired: () => void };
const labels: Record<string, string> = { importe: 'Importe por pedido ($)', preparacion: 'Preparación (min)', entrega: 'Entrega (min)', stock: 'Stock' };
const number = (value: string | null) => value === null ? 'Sin muestras' : Number(value).toLocaleString('es-AR', { maximumFractionDigits: 6 });
function utcDate(offset: number) { const date = new Date(); date.setUTCDate(date.getUTCDate() + offset); return date.toISOString().slice(0, 10); }

export default function Analytics({ restaurant, view = 'forecast', onSessionExpired }: Props) {
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [period, setPeriod] = useState({ inicio: utcDate(-7), fin: utcDate(-1) });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const base = `restaurantes/${restaurant}`;

  function failed(failure: unknown) {
    if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
    else setError(failure instanceof Error ? failure.message : 'No se pudo completar la operación.');
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); }
    catch (failure) { failed(failure); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      operationRequest<Forecast>(`${base}/predicciones`, undefined, controller.signal),
      operationRequest<Alert[]>(`${base}/alertas`, undefined, controller.signal),
    ]).then(([saved, storedAlerts]) => { setForecast(saved); setAlerts(storedAlerts); })
      .catch((failure: unknown) => { if (!controller.signal.aborted) failed(failure); });
    return () => controller.abort();
  }, [restaurant]);

  return <section id="analitica-restaurante" className="menu-manager" aria-label="Predicción e indicadores">
    {error && <p role="alert" className="auth-error">{error}</p>}
    {view === 'forecast' && <><h2>Prepará tu próxima semana</h2>
    <p>Regresión lineal por producto con pedidos entregados de días completos en UTC. Requiere 7 días de historial y 10 pedidos completados.</p>
    <div className="menu-actions">
      <button disabled={busy} onClick={() => void run(async () => setForecast(await operationRequest<Forecast>(`${base}/predicciones`, {}, undefined, 'POST')))}>Generar predicción (7 días)</button>
      <button disabled={busy} onClick={() => void run(async () => setForecast(await operationRequest<Forecast>(`${base}/predicciones`)))}>Consultar última predicción guardada</button>
    </div>
    {forecast && <>
      <p role="status" className="menu-notice">{forecast.estado}</p>
      {forecast.dias_historial !== null && <p>Historial: {forecast.dias_historial} día(s) · Pedidos completados: {forecast.pedidos_completados}</p>}
      {forecast.dias_validacion !== null && <p>Validación cronológica: últimos {forecast.dias_validacion} días. MAE mide error medio en unidades por día; menor es mejor.</p>}
      <p>Las estimaciones negativas del modelo se limitan a cero. Las cantidades son estimaciones, no ventas confirmadas.</p>
      <div className="catalog-grid">{forecast.predicciones.map((row) => <article className="product-card" key={row.id_prediccion}>
        <h3>{row.producto}</h3><p>{row.periodo_inicio} a {row.periodo_fin} UTC</p>
        <p>Demanda estimada total: {number(row.demanda_estimada)} unidades</p>
        <p>{row.nombre_metrica}: {number(row.valor_metrica)} unidades/día</p>
        <p>Guardada: {new Date(row.generada_en).toLocaleString('es-AR')}</p><p className="scope-note">Modelo: regresión lineal diaria.</p>
      </article>)}</div>
      {forecast.productos_sin_ventas.length > 0 && <p>Sin ventas históricas para entrenar: {forecast.productos_sin_ventas.join(', ')}.</p>}
      {forecast.predicciones.length > 0 && <><h3>Insumos necesarios y stock actual</h3>
        {forecast.recetas_faltantes.length > 0 && <p role="alert" className="auth-error">Cálculo parcial: faltan recetas de {forecast.recetas_faltantes.join(', ')}.</p>}
        <ul>{forecast.insumos.map((row) => <li key={row.id_insumo}>{row.nombre} ({row.unidad}): necesario {number(row.cantidad_necesaria)}, stock {number(row.stock_actual)}, faltante {number(row.faltante)}</li>)}</ul>
      </>}
    </>}
    </>}
    {view === 'metrics' && <><h2>Conocé tu operación</h2>
    <form className="menu-form" onSubmit={(event) => { event.preventDefault(); void run(async () => {
      const result = await operationRequest<Metrics>(`${base}/indicadores`, period, undefined, 'POST');
      setMetrics(result); setAlerts(result.alertas);
    }); }}>
      <div className="form-columns"><div><label htmlFor="metrics-start">Inicio del período (UTC)</label>
        <input id="metrics-start" type="date" required disabled={busy} max={period.fin} value={period.inicio} onChange={(event) => setPeriod({ ...period, inicio: event.target.value })} /></div>
        <div><label htmlFor="metrics-end">Fin del período (UTC, incluido)</label>
          <input id="metrics-end" type="date" required disabled={busy} min={period.inicio} max={utcDate(0)} value={period.fin} onChange={(event) => setPeriod({ ...period, fin: event.target.value })} /></div></div>
      <button disabled={busy}>Calcular indicadores y alertas</button>
    </form>
    <p>Referencia: período inmediatamente anterior de igual duración. Se alerta al superar el 110 % de su promedio. Stock negativo: umbral cero.</p>
    {metrics && <>
      <p>Período calculado: {metrics.inicio} a {metrics.fin} UTC. Referencia: {metrics.referencia_inicio} a {metrics.referencia_fin} UTC.</p>
      <div className="catalog-grid">{Object.entries(metrics.promedios).map(([key, value]) => <article className="product-card" key={key}>
        <h3>{labels[key]}</h3><p>Promedio: {number(value)} · Muestras: {metrics.muestras[key]}</p>
        <p>Promedio de referencia: {number(metrics.promedios_referencia[key])} · Muestras: {metrics.muestras_referencia[key]}</p>
        {metrics.promedios_referencia[key] === null && <p>Sin datos de referencia: no se genera alerta para este indicador.</p>}
      </article>)}</div>
      <h3>Stock y disponibilidad actuales</h3><p>Estas consultas muestran el estado actual, no una reconstrucción histórica del período.</p>
      <ul>{metrics.stock.map((row) => <li key={row.id_insumo}>{row.nombre}: {number(row.stock_actual)} {row.unidad}</li>)}</ul>
      <p>{metrics.repartidores.delivery_disponible ? 'Delivery disponible' : 'Delivery no disponible'}</p>
      <ul>{metrics.repartidores.repartidores.map((row) => <li key={row.id_repartidor}>{row.nombre}: {row.estado_disponibilidad} · {row.activo ? 'cuenta activa' : 'cuenta inactiva'}</li>)}</ul>
    </>}
    <h3>Alertas guardadas del restaurante (últimas 100)</h3>
    <button disabled={busy} onClick={() => void run(async () => setAlerts(await operationRequest<Alert[]>(`${base}/alertas`)))}>Consultar alertas guardadas</button>
    {!alerts.length && <p>No hay alertas guardadas.</p>}
    <div className="catalog-grid">{alerts.map((row) => <article className="product-card" key={row.id_alerta}>
      <h3>{labels[row.tipo] ?? row.tipo} · {row.estado}</h3><p>{row.descripcion}</p>
      <p>Valor observado: {number(row.valor_observado)} · Umbral: {number(row.valor_referencia)}</p>
      <p>Primera detección: {new Date(row.fecha_hora).toLocaleString('es-AR')}</p>
    </article>)}</div>
    </>}
  </section>;
}
