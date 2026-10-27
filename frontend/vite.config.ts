import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Proxy exclusivo del entorno local: el navegador utiliza un único origen.
const proxy = {
  '/api': 'http://127.0.0.1:8001',
};

export default defineConfig({
  plugins: [react()],
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
});
