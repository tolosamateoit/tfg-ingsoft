# Frontend local

Con FastAPI iniciado en `127.0.0.1:8001`, ejecutar `npm run dev` desde esta
carpeta y abrir `http://127.0.0.1:5173`. Las páginas usan rutas `#/...` y
conservan la sesión y la navegación al recargar.

Los tres accesos por perfil son exclusivos del servidor local de desarrollo.
Su configuración está en `.env.development.local`, ignorado por Git; la
plantilla `.env.example` no contiene credenciales. Las variables `LOCAL_ACCOUNT_*`
son privadas del servidor Vite: **no usar `VITE_*` para credenciales**. Reiniciar
Vite después de cambiarlas. Cada acceso utiliza el login real de FastAPI,
incluidos contraseña, bloqueo y sesión. Solo se permite desde loopback y el
mismo origen. No habilitar este servidor de desarrollo en una red pública.

`npm run build` comprueba TypeScript y genera la versión pública, sin los
accesos locales ni sus credenciales. No cambia los endpoints del backend.

Las fotografías ilustrativas se mantienen en `public/images/food-atlas.png`;
no se incorporaron campos de imagen a la base de datos.
