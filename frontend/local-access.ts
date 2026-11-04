import type { Plugin } from 'vite';

// Exclusivo del servidor de desarrollo. Estas variables nunca se envían a React.
export function localAccess(env: Record<string, string>): Plugin {
  const roles = ['propietario', 'personal', 'repartidor', 'repartidor_2', 'repartidor_3', 'cliente'];
  return {
    name: 'private-local-account-access', apply: 'serve',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const role = req.headers['x-local-account'];
        if (req.url !== '/api/auth/login' || !role) return next();
        const host = req.headers.host ?? '';
        const origin = req.headers.origin;
        const tab = req.headers['x-oliva-tab'];
        const localHost = /^(127\.0\.0\.[12]|localhost|\[::1\]):\d+$/.test(host);
        const localPeer = /^(::ffff:)?127\./.test(req.socket.remoteAddress ?? '') || req.socket.remoteAddress === '::1';
        if (req.method !== 'POST' || !localHost || !localPeer || origin !== `http://${host}`
            || req.headers['x-csrf-protection'] !== '1' || typeof role !== 'string' || !roles.includes(role)
            || (tab !== undefined && (typeof tab !== 'string' || !/^[a-f0-9]{32}$/.test(tab)))) {
          res.writeHead(403, { 'Content-Type': 'application/json' });
          return res.end(JSON.stringify({ detail: 'Acceso local no permitido.' }));
        }
        const correo = env[`LOCAL_ACCOUNT_${role.toUpperCase()}_EMAIL`];
        const contrasena = env.LOCAL_ACCOUNT_PASSWORD;
        if (!correo || !contrasena) {
          res.writeHead(404, { 'Content-Type': 'application/json' });
          return res.end(JSON.stringify({ detail: 'Acceso local no configurado.' }));
        }
        req.resume();
        try {
          const target = server.config.server.proxy?.['/api'];
          const backend = typeof target === 'string' ? target : target?.target;
          if (typeof backend !== 'string') throw new Error('Missing local proxy');
          const response = await fetch(`${backend}/api/auth/login`, {
            method: 'POST', redirect: 'error', signal: AbortSignal.timeout(12000),
            headers: { 'Content-Type': 'application/json', Origin: origin, 'X-CSRF-Protection': '1', ...(typeof tab === 'string' ? { 'X-Oliva-Tab': tab } : {}) },
            body: JSON.stringify({ correo, contrasena }),
          });
          res.statusCode = response.status;
          res.setHeader('Content-Type', 'application/json');
          res.setHeader('Cache-Control', 'no-store');
          const cookies = response.headers.getSetCookie();
          if (cookies.length) res.setHeader('Set-Cookie', cookies);
          res.end(await response.text());
        } catch {
          res.writeHead(503, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
          res.end(JSON.stringify({ detail: 'El servicio de acceso no está disponible.' }));
        }
      });
    },
  };
}
