import { formatDateTime } from '../services/format';
import { useState, type FormEvent } from 'react';
import { operationRequest } from '../services/operations';
import { OrderError } from '../services/orders';
import { roleLabels } from './navigation';

type Diagnostic = {
  id_usuario: number; correo: string; rol: string; activo: boolean; id_restaurante: number | null;
  rol_reconocido: boolean; pertenencia_configurada: boolean; perfil_operativo_completo: boolean;
  bloqueo_temporal: boolean; bloqueado_hasta: string | null; acceso_habilitado: boolean;
};

export default function AccountSupport({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [email, setEmail] = useState('');
  const [data, setData] = useState<Diagnostic | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); setData(null);
    try { setData(await operationRequest<Diagnostic>('admin/diagnostico-cuenta', { correo: email }, undefined, 'POST')); }
    catch (failure) {
      if (failure instanceof OrderError && failure.status === 401) onSessionExpired();
      else setError(failure instanceof Error ? failure.message : 'No se pudo consultar la cuenta.');
    } finally { setBusy(false); }
  }
  return <section className="menu-manager" aria-label="Administración y soporte de cuentas">
    <h2>Diagnóstico de cuentas</h2>
    <p>Diagnóstico de una cuenta por correo exacto. Esta consulta es de solo lectura y no otorga acceso a los datos operativos del restaurante.</p>
    <form className="menu-form" onSubmit={(event) => void submit(event)}>
      <label htmlFor="support-email">Correo de la cuenta a diagnosticar</label>
      <input id="support-email" type="email" required maxLength={254} autoComplete="off" value={email} disabled={busy} onChange={(event) => setEmail(event.target.value)} />
      <button disabled={busy}>{busy ? 'Consultando…' : 'Consultar diagnóstico'}</button>
    </form>
    {error && <p role="alert" className="auth-error">{error}</p>}
    {data && <article className="product-card"><h3>{data.correo}</h3>
      <dl className="session-details"><dt>Identificador de cuenta</dt><dd>{data.id_usuario}</dd>
        <dt>Estado</dt><dd>{data.activo ? 'Activa' : 'Inactiva'}</dd><dt>Rol</dt><dd>{roleLabels[data.rol] ?? data.rol} · {data.rol_reconocido ? 'Reconocido' : 'No reconocido'}</dd>
        <dt>Restaurante asociado</dt><dd>{data.id_restaurante ?? 'Sin restaurante asociado'}</dd>
        <dt>Pertenencia requerida por el rol</dt><dd>{data.pertenencia_configurada ? 'Configuración válida' : 'Falta restaurante asociado'}</dd>
        <dt>Perfil operativo</dt><dd>{data.perfil_operativo_completo ? 'Completo o no requerido' : 'Falta el perfil de cliente o repartidor'}</dd>
        <dt>Bloqueo temporal</dt><dd>{data.bloqueo_temporal && data.bloqueado_hasta ? `Bloqueada hasta ${formatDateTime(data.bloqueado_hasta)}` : 'Sin bloqueo vigente'}</dd>
        <dt>Condiciones de acceso</dt><dd>{data.acceso_habilitado ? 'Habilitadas; se requiere una contraseña válida' : 'La cuenta no cumple las condiciones para iniciar sesión'}</dd>
      </dl>
    </article>}
  </section>;
}
