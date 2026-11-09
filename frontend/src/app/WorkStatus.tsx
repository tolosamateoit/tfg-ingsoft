import { useState } from 'react';
import { useApiQuery } from '../services/useApiQuery';
import { operationRequest, type CourierPage } from '../services/operations';

export default function WorkStatus({ restaurant, courier, onSessionExpired }: {restaurant: number; courier: boolean; onSessionExpired: () => void}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const path = courier ? 'repartidores/me' : `restaurantes/${restaurant}/estado`;
  const query = useApiQuery<{abierto: boolean} | CourierPage>(path, signal => operationRequest(path, undefined, signal), onSessionExpired, {interval: 10000});
  const row = courier ? (query.data as CourierPage | undefined)?.repartidores[0] : undefined;
  const active = courier ? row?.estado_disponibilidad === 'Disponible' : query.data?.abierto;
  async function toggle() {
    setBusy(true); setError('');
    try {
      await operationRequest(path, courier ? {estado_disponibilidad: active ? 'No disponible' : 'Disponible'} : {abierto: !active});
      await query.refetch();
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'No se pudo cambiar el estado.'); }
    finally { setBusy(false); }
  }
  return <div className="work-status">{query.data && <button type="button" disabled={busy || Boolean(courier && !active && row?.entrega_activa)} onClick={() => void toggle()}>
    {courier ? (active ? '● Disponible' : '● No disponible') : (active ? '● Abierto' : '● Cerrado')}
  </button>}{row?.entrega_activa && <small>Tenés una entrega activa.</small>}{(error || query.error) && <small role="alert">{error || query.error?.message}</small>}</div>;
}
