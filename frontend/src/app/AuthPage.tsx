import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { AuthError, getSession, login, logout, type User } from '../services/auth';
import MenuManager from './MenuManager';

const roles: Record<string, string> = {
  cliente: 'Cliente', personal: 'Personal del restaurante', propietario: 'Propietario',
  repartidor: 'Repartidor', administrador_plataforma: 'Administrador de la plataforma',
};

export default function AuthPage() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const canManageMenu = user !== null && user.id_restaurante !== null && ['personal', 'propietario'].includes(user.rol);
  const sessionExpired = useCallback(() => { setUser(null); setError('Tu sesión venció. Volvé a ingresar.'); }, []);

  useEffect(() => {
    const controller = new AbortController();
    void getSession(controller.signal).then((session) => {
      if (!controller.signal.aborted) setUser(session);
    }).catch(() => {
      if (!controller.signal.aborted) setError('No se pudo comprobar la sesión. Podés volver a intentar iniciar sesión.');
    }).finally(() => {
      if (!controller.signal.aborted) setChecking(false);
    });
    return () => controller.abort();
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try { setUser(await login(email, password)); }
    catch (failure) {
      setError(failure instanceof AuthError ? failure.message : 'No se pudo conectar con el servidor. Volvé a intentar.');
    } finally {
      setPassword('');
      setBusy(false);
    }
  }

  async function signOut() {
    setBusy(true);
    setError('');
    try { await logout(); setUser(null); }
    catch { setError('No se pudo cerrar la sesión. Volvé a intentar.'); }
    finally { setBusy(false); }
  }

  return (
    <div className="page">
      <header className="page-header">
        <span className="brand">Pedidos y delivery</span>
        <span className="demo-label">Demo académica</span>
      </header>
      <main className={canManageMenu ? 'management-main' : 'auth-main'}>
        <p className="eyebrow">Ingeniería en Software · HU-01</p>
        <h1>{user ? 'Sesión iniciada' : 'Iniciar sesión'}</h1>
        <p className="intro">Acceso para usuarios de prueba del prototipo.</p>
        <section className="connection-card" aria-label="Autenticación" aria-busy={busy || checking}>
          {checking ? <p role="status">Comprobando sesión…</p> : user ? (
            <>
              <h2>Hola, {user.nombre}</h2>
              <dl className="session-details">
                <dt>Correo</dt><dd>{user.correo}</dd>
                <dt>Rol</dt><dd>{roles[user.rol] ?? user.rol}</dd>
                <dt>Ámbito de acceso</dt><dd>{user.id_restaurante !== null
                  ? `Restaurante ${user.id_restaurante}`
                  : user.rol === 'cliente' ? 'Tus propios pedidos en los restaurantes'
                    : 'Cuenta de plataforma sin acceso operativo global'}</dd>
              </dl>
              <p>{canManageMenu ? 'Gestioná los productos y las recetas de tu restaurante.' : 'Las funciones de tu rol se incorporarán en las próximas etapas.'}</p>
              <button type="button" disabled={busy} onClick={() => void signOut()}>
                {busy ? 'Cerrando sesión…' : 'Cerrar sesión'}
              </button>
            </>
          ) : (
            <form onSubmit={(event) => void signIn(event)} className="login-form">
              <label htmlFor="email">Correo electrónico</label>
              <input id="email" name="email" type="email" autoComplete="username" required maxLength={254}
                value={email} onChange={(event) => setEmail(event.target.value)} disabled={busy} />
              <label htmlFor="password">Contraseña</label>
              <input id="password" name="password" type="password" autoComplete="current-password" required maxLength={128}
                value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} />
              <button type="submit" disabled={busy}>{busy ? 'Ingresando…' : 'Ingresar'}</button>
              <p className="scope-note">Después de 5 intentos fallidos consecutivos, el ingreso se bloquea durante 15 minutos.</p>
              <p className="scope-note">La recuperación de contraseña por correo no está disponible en este prototipo.</p>
            </form>
          )}
          {error && <p className="auth-error" role="alert">{error}</p>}
        </section>
        {canManageMenu && user && user.id_restaurante !== null && <MenuManager key={user.id_restaurante} restaurant={user.id_restaurante} onSessionExpired={sessionExpired} />}
      </main>
      <footer>Prototipo de tesis · Desarrollo por etapas</footer>
    </div>
  );
}
