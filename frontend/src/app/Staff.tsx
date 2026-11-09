
import { useState, type FormEvent } from 'react';
import { useApiQuery } from '../services/useApiQuery';
import { operationRequest } from '../services/operations';

type StaffMember = {id_usuario: number; nombre: string; correo: string; activo: boolean};

export default function Staff({restaurant, onSessionExpired}: {restaurant: number; onSessionExpired: () => void}) {
  const path = `restaurantes/${restaurant}/personal`;
  const query = useApiQuery<StaffMember[]>(path, signal => operationRequest(path, undefined, signal), onSessionExpired);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function run(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); await query.refetch(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'No se pudo completar la operación.'); }
    finally { setBusy(false); }
  }

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    void run(async () => { await operationRequest(path, {nombre: data.get('nombre'), correo: data.get('correo'), contrasena: data.get('contrasena')}, undefined, 'POST'); form.reset(); });
  }

  return <section className="menu-manager">
    <h2>Personal del restaurante</h2>

    <form onSubmit={create} className="login-form">
      <label>Nombre<input name="nombre" required maxLength={150}/></label>
      <label>Correo<input name="correo" type="email" required maxLength={254}/></label>
      <label>Contraseña<input name="contrasena" type="password" required minLength={15} maxLength={20} autoComplete="new-password"/></label>
      <button className="primary-button" disabled={busy}>Crear cuenta de personal</button>
    </form>

    {(error || query.error) && <p role="alert" className="auth-error">{error || query.error?.message}</p>}

    <br />
    <br />

    <h3>Empleados registrados</h3>

    <br />

    {query.data?.map(person =>
      <article className="surface-card" key={person.id_usuario}>
        <strong>{person.nombre}</strong>
        <p>{person.correo} · {person.activo ? 'Activa' : 'Inactiva'}</p>
      </article>
    )}
  </section>;
}
