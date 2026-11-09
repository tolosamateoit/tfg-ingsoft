import { useApiQuery } from '../services/useApiQuery';
import { formatCalendarDate } from '../services/format';
import OperationalAnalytics from './OperationalAnalytics';
import { useEffect, useState } from 'react';
import { operationRequest } from '../services/operations';
import type { DayForecast } from '../services/analytics';

type Props = { restaurant: number; view?: 'forecast' | 'metrics'; onSessionExpired: () => void };
const inventoryAmount = (value: string, unit: string) => {
  const amount = Number(value);
  const whole = ['unidad', 'unidades', 'u'].includes(unit.toLowerCase());
  const label = whole ? 'un.' : ['l', 'litro', 'litros'].includes(unit.toLowerCase()) ? 'L' : unit;
  const formatted = !whole && amount !== 0 && Math.abs(amount) < 0.01
    ? (amount > 0 ? '<0,01' : '>−0,01')
    : amount.toLocaleString('es-AR', { maximumFractionDigits: whole ? 0 : 2 });
  return `${formatted} ${label}`;
};

export function ForecastDetails({ forecast, onSelect, busy = false, selectedDate }: {
  forecast: DayForecast; onSelect?: (date: string) => void; busy?: boolean; selectedDate?: string | null;
}) {
  const shortages = forecast.insumos.filter((row) => Number(row.faltante) > 0);
  const selected = selectedDate ?? forecast.fecha_seleccionada;
  return <div className="demand-forecast" aria-busy={busy}>
    <header className="forecast-heading">
      <h2>¿Qué vas a necesitar vender?</h2><p>Elegí el día y prepará tu rotisería.</p></header>
    <div className="forecast-days" role="group" aria-label="Elegir fecha de previsión">
      {forecast.fechas_disponibles.map((option) => <button key={option.fecha} type="button"
        aria-pressed={selected === option.fecha} onClick={() => onSelect?.(option.fecha)}>
        <span>{option.etiqueta.split(' ')[0]}</span><strong>{option.etiqueta.split(' ')[1]}</strong>
      </button>)}
    </div>
    {busy ? <p className="forecast-loading" role="status">Calculando lo que vas a necesitar…</p> : <>
      {forecast.aviso && <p role="status" className="forecast-notice">{forecast.aviso}</p>}
      {forecast.pedidos_estimados !== null && <>
        <p className="forecast-date">Para el {formatCalendarDate(forecast.fecha_seleccionada!)}</p>
        <div className="forecast-summary">
          <div><strong>{forecast.pedidos_estimados}</strong><span>pedidos estimados</span></div>
          <div className={forecast.cantidad_faltantes ? 'forecast-shortage' : 'forecast-covered'}>
            <strong>{forecast.cantidad_faltantes}</strong><span>insumos con faltantes</span></div>
        </div>
        <section className="forecast-section" aria-labelledby="forecast-products-title">
          <h3 id="forecast-products-title">Productos que conviene preparar</h3>
          <div className="forecast-products">{forecast.productos.filter((row) => row.cantidad > 0).map((row) =>
            <article className="forecast-product" key={`${forecast.fecha_seleccionada}-${row.id_producto}`}><h4>{row.nombre}</h4>
              <p><strong>{row.cantidad}</strong><span>unidades</span></p>
              <details className="forecast-product-history"><summary aria-label={`Ver detalle de ventas de ${row.nombre}`}><span aria-hidden="true">⌄</span></summary>
                <div><strong>Ventas utilizadas</strong><small>{row.historial_ventas.length} de 7 días operativos</small>
                  <ul>{row.historial_ventas.map((day) => <li key={day.fecha}>{formatCalendarDate(day.fecha)}: {day.unidades} {day.unidades === 1 ? 'unidad' : 'unidades'}</li>)}</ul>
                  <p>Promedio: {Number(row.estimacion_original).toLocaleString('es-AR', {maximumFractionDigits: 6})} unidades.</p>
                  {Number(row.estimacion_original) !== row.cantidad && <p>Redondeado hacia arriba: {row.cantidad} unidades.</p>}
                </div></details></article>)}</div>
          {forecast.productos.every((row) => row.cantidad === 0) && <p>No se prevén unidades para preparar este día.</p>}
        </section>
        <section className="forecast-section" aria-labelledby="forecast-shopping-title">
          <h3 id="forecast-shopping-title">Qué necesitás comprar</h3>
          {shortages.length ? <ul className="forecast-shopping">{shortages.map((row) =>
            <li key={row.id_insumo}><div><strong>{row.nombre}</strong>
              <span>Disponible: {inventoryAmount(row.stock_actual, row.unidad)}</span></div>
              <div className="forecast-buy"><span>Comprar</span><strong>{inventoryAmount(row.reposicion_sugerida, row.unidad)}</strong></div></li>)}</ul>
            : forecast.compras_completas ? <p className="forecast-success">¡Tenés stock suficiente para lo previsto!</p>
              : <p className="forecast-notice">Completá las recetas para revisar todas las compras.</p>}
        </section>
        <aside className="forecast-reason"><h3>Por qué esta recomendación</h3><p>{forecast.explicaciones.join(' ')}</p></aside>
        <p className="forecast-footnote">Una guía para preparar tu día. Las cantidades son estimadas.</p>
      </>}
    </>}
  </div>;
}

function DemandForecast({ restaurant, onSessionExpired }: Omit<Props, 'view'>) {
  const [selected, setSelected] = useState<string | null>(null);
  const path = `restaurantes/${restaurant}/predicciones/diaria${selected ? `?fecha=${encodeURIComponent(selected)}` : ''}`;
  const query = useApiQuery<DayForecast>(path, (signal) => operationRequest(path, undefined, signal), onSessionExpired);
  const [previous, setPrevious] = useState<DayForecast | null>(null);
  useEffect(() => { if (query.data) setPrevious(query.data); }, [query.data]);
  const forecast = query.data ?? previous;
  const loading = query.isPending;
  const failure = query.error?.message;
  return <>
    {failure && <p role="alert" className="auth-error">{failure} <button onClick={() => void query.refetch()}>Reintentar</button></p>}
    {forecast && <button disabled={query.isFetching} onClick={() => void query.refetch()}>Actualizar previsión</button>}
    {forecast ? <ForecastDetails forecast={forecast} selectedDate={selected} onSelect={setSelected}
      busy={loading || Boolean(failure) || Boolean(selected && selected !== forecast.fecha_seleccionada)}/>
      : <><h2>¿Qué vas a necesitar vender?</h2>{loading && <p role="status">Cargando tu previsión…</p>}</>}
  </>;
}

export default function Analytics({ restaurant, view = 'forecast', onSessionExpired }: Props) {
  return view === 'metrics' ? <OperationalAnalytics key={restaurant} restaurant={restaurant} onSessionExpired={onSessionExpired}/>
    : <section id="analitica-restaurante" className="menu-manager" aria-label="Previsión de demanda">
      <DemandForecast key={restaurant} restaurant={restaurant} onSessionExpired={onSessionExpired}/>
    </section>;
}
