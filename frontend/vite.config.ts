import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { localAccess } from './local-access';

// Proxy exclusivo del entorno local: el navegador utiliza un único origen.
const apiTarget = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8001';
const proxy = {
  '/api': {
    target: apiTarget,
    changeOrigin: true,
  },
};

export default defineConfig(({ command, mode }) => {
 const local = loadEnv(mode, process.cwd(), 'LOCAL_ACCOUNT_');
 const enabled = command === 'serve' && mode === 'development' && Boolean(local.LOCAL_ACCOUNT_PASSWORD)
   && ['PROPIETARIO', 'PERSONAL', 'REPARTIDOR'].every((role) => Boolean(local[`LOCAL_ACCOUNT_${role}_EMAIL`]));
 return {
  plugins: [react(), ...(enabled ? [localAccess(local)] : [])],
  define: { __LOCAL_ACCOUNT_ACCESS__: JSON.stringify(enabled) },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy,
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    proxy,
  },
 };
});
