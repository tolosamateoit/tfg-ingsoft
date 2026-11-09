import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient, startQuerySession, clearQuerySession } from '../services/queryCache';
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { AuthError, getSession, localAccountLogin, login, logout, type User } from '../services/auth';
import MenuManager from './MenuManager';
import Inventory from './Inventory';
import Orders from './Orders';
import Couriers from './Couriers';
import Logistics from './Logistics';
import Analytics from './Analytics';
import AccountSupport from './AccountSupport';
import WorkStatus from './WorkStatus';
import Staff from './Staff';
import { Icon, FoodPhoto } from './ui';
import { canonicalPath, newOrder, pagesFor, roleLabels } from './navigation';

export default function AuthPage() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [path, setPath] = useState(window.location.hash.replace(/^#\//, ''));
  const [mobileMenu, setMobileMenu] = useState(false);
  const sessionExpired = useCallback(() => { clearQuerySession(); setUser(null); setError('Tu sesión venció. Volvé a ingresar.'); }, []);
  const staff = user !== null && user.id_restaurante !== null && ['propietario', 'personal'].includes(user.rol);
  const pages = user ? pagesFor(user) : [];
  const current = pages.find((page) => page.path === canonicalPath(path)) ?? (staff && path === newOrder.path ? newOrder : pages[0]);
  useEffect(() => {
    const changed = () => { setPath(window.location.hash.replace(/^#\//, '')); setMobileMenu(false); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  useEffect(() => {
    if (current && current.path !== path) { window.history.replaceState(null, '', `#/${current.path}`); setPath(current.path); }
    document.title = current ? `${current.label} · Oliva` : 'Ingresar · Oliva';
  }, [current?.path, path]);
  useEffect(() => {
    const controller = new AbortController();
    void getSession(controller.signal).then((session) => { if (!controller.signal.aborted) { if (session) startQuerySession(session); else clearQuerySession(); setUser(session); } })
      .catch(() => { if (!controller.signal.aborted) setError('No se pudo comprobar tu sesión. Volvé a intentar.'); })
      .finally(() => { if (!controller.signal.aborted) setChecking(false); });
    return () => controller.abort();
  }, []);
  function enter(session: User) {
    startQuerySession(session);
    const home = pagesFor(session)[0].path;
    window.history.replaceState(null, '', `#/${home}`);
    setPath(home); setUser(session); setMobileMenu(false);
  }
  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    try { enter(await login(email, password)); }
    catch (failure) { setError(failure instanceof AuthError ? failure.message : 'No se pudo conectar con el servidor.'); }
    finally { setPassword(''); setShowPassword(false); setBusy(false); }
  }
  async function quickAccess(role: string) {
    setBusy(true); setError('');
    try { enter(await localAccountLogin(role)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'No se pudo iniciar sesión.'); }
    finally { setBusy(false); setPassword(''); }
  }
  async function signOut() {
    setBusy(true); setError('');
    try { await logout(); clearQuerySession(); setUser(null); setMobileMenu(false); }
    catch { setError('No se pudo cerrar la sesión. Volvé a intentar.'); }
    finally { setBusy(false); }
  }
  const brand = <><span className="brand-mark"><Icon name="leaf" size={24}/></span><span>oliva<span className="brand-dot">.</span></span></>;
  if (checking) return <div className="session-loading"><div className="app-brand">{brand}</div><span className="loading-ring"/><p>Preparando tu espacio…</p></div>;
  if (!user) return <div className="login-page">
    <div className="login-visual"><div className="app-brand">{brand}</div><div className="login-story"><span className="eyebrow">HECHO PARA TU RESTAURANTE</span><h1>Cada pedido,<br/>en su punto.</h1>
      <p>Tu cocina, tu equipo y tus entregas.<br/>Todo conectado, de principio a fin.</p><div className="login-dish"><FoodPhoto name="Milanesa" hero/><div className="dish-label"><span className="dish-check"><Icon name="check"/></span><div><strong>El sabor de trabajar mejor</strong><small>Más orden. Más tiempo para lo que importa.</small></div></div></div>
    </div><span className="login-footnote">Oliva · Gestión gastronómica</span></div>
    <main className="login-main"><div className="login-panel"><span className="eyebrow">TU ESPACIO DE TRABAJO</span><h2>Bienvenido de nuevo</h2><p className="login-intro">Ingresá y poné tu restaurante en marcha.</p>
      <form className="login-form" onSubmit={(event) => void signIn(event)}>
        <label htmlFor="email">Correo electrónico</label><input id="email" type="email" autoComplete="username" placeholder="tu@restaurante.com" required maxLength={254} disabled={busy} value={email} onChange={(event) => setEmail(event.target.value)}/>
        <label htmlFor="password">Contraseña</label><div className="password-field"><input id="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" placeholder="Ingresá tu contraseña" required maxLength={128} disabled={busy} value={password} onChange={(event) => setPassword(event.target.value)}/>
          <button type="button" className="icon-button" aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'} aria-pressed={showPassword} onClick={() => setShowPassword(!showPassword)}><Icon name={showPassword ? 'eyeOff' : 'eye'}/></button></div>
        <button className="primary-button login-submit" disabled={busy}>{busy ? 'Ingresando…' : 'Ingresar a mi espacio'}<Icon name="arrow"/></button>
      </form>{error && <p className="auth-error" role="alert">{error}</p>}
      {import.meta.env.DEV && __LOCAL_ACCOUNT_ACCESS__ && <div className="quick-access"><div className="divider-label"><span>Acceso rápido</span></div><div className="quick-access-grid">
        {[['propietario','Propietario','grid'],['personal','Personal','food'],['repartidor','Repartidor 1','truck'],['repartidor_2','Repartidor 2','truck'],['repartidor_3','Repartidor 3','truck'],['cliente','Cliente','people']].map(([role,label,icon]) => <button key={role} disabled={busy} onClick={() => void quickAccess(role)}><Icon name={icon} size={22}/><span>{label}</span></button>)}
      </div></div>}<p className="login-security"><Icon name="check" size={16}/>Acceso protegido para tu equipo</p>
    </div><footer>Todo listo para un buen servicio.</footer></main>
  </div>;
  const initials = user.nombre.split(' ').filter(Boolean).slice(0,2).map((word) => word[0]).join('').toUpperCase();
  return <QueryClientProvider client={queryClient}><div className={`app-shell${user.rol === 'cliente' ? ' app-shell--customer' : ''}`}>
    {mobileMenu && <button className="sidebar-scrim" aria-label="Cerrar navegación" onClick={() => setMobileMenu(false)}/>}
    <aside className={`sidebar${mobileMenu ? ' sidebar--open' : ''}`}><a href={`#/${pages[0].path}`} className="app-brand" aria-label="Oliva, inicio">{brand}</a>
      <div className="workspace-pill"><span className="workspace-avatar"><Icon name="food"/></span><div><strong>{user.id_restaurante ? (user.restaurante ?? 'Mi restaurante') : user.rol === 'cliente' ? 'Mi espacio' : 'Oliva'}</strong><small>{roleLabels[user.rol]}</small></div></div>
      {user.id_restaurante !== null && ['propietario', 'repartidor'].includes(user.rol) && <WorkStatus restaurant={user.id_restaurante} courier={user.rol === 'repartidor'} onSessionExpired={sessionExpired}/>}
      <nav aria-label="Navegación principal">{pages.map((page, index) => <div key={page.path}>{(index === 0 || pages[index-1].group !== page.group) && <p className="nav-group">{page.group}</p>}
        <a href={`#/${page.path}`} className={`nav-link${current.path === page.path ? ' nav-link--active' : ''}`} aria-current={current.path === page.path ? 'page' : undefined}><Icon name={page.icon}/>{page.label}{current.path === page.path && <span className="nav-active-dot"/>}</a>
      </div>)}</nav>
      <div className="sidebar-bottom"><span className="sidebar-tagline"><Icon name="leaf" size={17}/>Un servicio a la vez.</span><div className="sidebar-user"><span className="avatar">{initials}</span><div><strong>{user.nombre}</strong><small>{roleLabels[user.rol]}</small></div><button className="icon-button" aria-label="Cerrar sesión" disabled={busy} onClick={() => void signOut()}><Icon name="logout"/></button></div></div>
    </aside>
    <div className="workspace"><header className="workspace-header"><div className="header-breadcrumb"><button className="icon-button mobile-menu" aria-label="Abrir navegación" aria-expanded={mobileMenu} onClick={() => setMobileMenu(!mobileMenu)}><Icon name="menu"/></button><span>Mi espacio</span><span className="breadcrumb-slash">/</span><strong>{current.label}</strong></div>
      <div className="header-actions"><span className="header-date">{new Date().toLocaleDateString('es-AR',{day:'numeric',month:'long'})}</span>{staff && <a href="#/nuevo-pedido" className="primary-button"><Icon name="plus" size={18}/>Nuevo pedido</a>}<span className="avatar avatar--small" title={user.nombre}>{initials}</span></div></header>
      <main className="workspace-main" id="main-content"><div className="page-intro"><div><span className="eyebrow">{current.group}</span><h1>{current.label}</h1><p>{current.description}</p></div>{current.path === 'resumen' && <span className="greeting-chip">Hola, {user.nombre.split(' ')[0]}<Icon name="leaf" size={17}/></span>}</div>
        {error && <p role="alert" className="auth-error">{error}</p>}<div className="page-content" key={`${user.id_usuario}-${user.id_restaurante}-${current.path}`}>
          {current.path === 'soporte' && <AccountSupport onSessionExpired={sessionExpired}/>}
          {staff && user.id_restaurante !== null && <>
            {current.path === 'catalogo' && <MenuManager owner={user.rol === 'propietario'} restaurant={user.id_restaurante} onSessionExpired={sessionExpired}/>}
            {current.path === 'stock' && <Inventory owner={user.rol === 'propietario'} restaurant={user.id_restaurante} onSessionExpired={sessionExpired}/>}
            {(current.path === 'pedidos' || current.path === 'nuevo-pedido') && <Orders restaurant={user.id_restaurante} view={current.path === 'nuevo-pedido' ? 'create' : 'list'} onSessionExpired={sessionExpired}/>}
            {current.path === 'repartidores' && <Couriers restaurant={user.id_restaurante} owner={user.rol === 'propietario'} onSessionExpired={sessionExpired}/>}
            {current.path === 'personal' && user.rol === 'propietario' && <Staff restaurant={user.id_restaurante} onSessionExpired={sessionExpired}/>}
            {current.path === 'entregas' && <Logistics restaurant={user.id_restaurante} courier={false} view="deliveries" onSessionExpired={sessionExpired}/>}
            {current.path === 'demanda' && <Analytics restaurant={user.id_restaurante} view="forecast" onSessionExpired={sessionExpired}/>}
            {current.path === 'indicadores' && <Analytics restaurant={user.id_restaurante} view="metrics" onSessionExpired={sessionExpired}/>}
          </>}
          {user.rol === 'repartidor' && user.id_restaurante !== null && (current.path === 'pedidos-reparto' ? <Logistics restaurant={user.id_restaurante} courier view="deliveries" onSessionExpired={sessionExpired}/> : <Couriers restaurant={null} onSessionExpired={sessionExpired}/>)}
          {user.rol === 'cliente' && <Orders restaurant={null} view={current.path === 'menu' ? 'menu' : 'list'} onSessionExpired={sessionExpired}/>}
        </div>
      </main><footer className="workspace-footer"><span>Oliva · Hecho para tu restaurante</span><span>Que sea un buen servicio.</span></footer>
    </div>
  </div></QueryClientProvider>;
}
