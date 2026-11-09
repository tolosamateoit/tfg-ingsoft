# Frontend local

Con FastAPI iniciado en `127.0.0.1:8001`, ejecutar `npm run dev` desde esta
carpeta y abrir `http://127.0.0.1:5173`. Las páginas usan rutas `#/...` y
conservan la sesión y la navegación al recargar.

Los accesos rápidos para la demostración funcionan únicamente en el servidor
local de desarrollo. Las cuentas se configuran en `.env.development.local`,
ignorado por Git, siguiendo `.env.example`. No usar variables `VITE_*` para
credenciales ni habilitar este servidor de desarrollo en una red pública.
Cada acceso utiliza el login de FastAPI, con sus permisos, bloqueo y sesión.

`npm run build` comprueba TypeScript y genera la versión pública, sin los
accesos locales ni sus credenciales. No cambia los endpoints del backend.

Las fotografías ilustrativas se mantienen en `public/images/food-atlas.png`;
no se incorporaron campos de imagen a la base de datos.
