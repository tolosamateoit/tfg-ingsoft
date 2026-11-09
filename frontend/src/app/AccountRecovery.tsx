import { useState, type FormEvent } from 'react';
import { operationRequest } from '../services/operations';
import { OrderError } from '../services/orders';

export default function AccountRecovery({ path }: {path: string}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState('');
  const [temporary, setTemporary] = useState('');
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await operationRequest<{contrasena_temporal: string}>(path,
        {contrasena_administrador: password}, undefined, 'POST');
      setTemporary(result.contrasena_temporal); setOpen(false);
    } catch (failure) {
      setError(failure instanceof OrderError && failure.status === 401 ? 'No se pudo verificar tu contraseña.' :
        failure instanceof Error ? failure.message : 'No se pudo restablecer la cuenta.');
    } finally { setPassword(''); setBusy(false); }
  }
  return <div>
    {!temporary && <button type="button" disabled={busy} onClick={() => setOpen(!open)}>Restablecer por compromiso</button>}
    {open && <form className="menu-form" onSubmit={event => void submit(event)}>
      <p>Se cerrarán las sesiones de esta cuenta y deberá cambiar la contraseña temporal al ingresar.</p>
      <label>Tu contraseña<input type="password" required autoComplete="current-password" disabled={busy} value={password} onChange={event => setPassword(event.target.value)}/></label>
      <button disabled={busy}>Generar contraseña temporal</button>
    </form>}
    {error && <p className="auth-error" role="alert">{error}</p>}
    {temporary && <p role="status">Contraseña temporal: <strong>{temporary}</strong>. Compartila de forma privada; se muestra una sola vez.</p>}
  </div>;
}
