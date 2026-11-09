# Demo académica · Pedidos y delivery

Proyecto académico con React/TypeScript, FastAPI y PostgreSQL. La aplicación
incluye autenticación, gestión de menú y recetas, pedidos, preparación,
inventario, logística y analítica. Esta guía cubre instalación, configuración,
pruebas y compilación local.

## Requisitos

- Node.js 22.12 o superior (se recomienda la versión LTS 24), con npm.
- Python 3.14, versión utilizada para verificar el backend.
- Dos terminales abiertas en la raíz del repositorio.

Podés comprobar las instalaciones con `node --version`, `npm --version` y
`python --version`. Si acabás de instalar Node.js, reiniciá la terminal del IDE.

## 1. Iniciar el backend

En la primera terminal, usando PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

No es necesario activar el entorno virtual ni cambiar la política de ejecución
de PowerShell. En las siguientes ejecuciones basta con el último comando desde
`backend/`.

- Endpoint de prueba: <http://127.0.0.1:8001/api/health>
- Documentación interactiva: <http://127.0.0.1:8001/docs>

Respuesta esperada del endpoint:

```json
{"status":"ok","message":"El backend está disponible."}
```

Es una comprobación técnica pública; no consulta ni expone datos de negocio.

## 2. Configurar PostgreSQL en Supabase

Antes de comprobar la base, completá estos pasos en tu cuenta de Supabase:

1. Abrí el proyecto destinado a esta demo. Si todavía no existe, crealo y esperá
   a que esté disponible. Guardá la contraseña de la base de datos de forma privada.
   Si está pausado, reanudalo. No hace falta crear tablas ni ejecutar SQL.
2. En el botón **Connect**, elegí **Session pooler**. Copiá por separado host,
   puerto, database y user exactamente como aparecen. Este modo permite usar
   redes IPv4; normalmente usa el puerto `5432`. No uses Transaction pooler (`6543`)
   para esta configuración inicial.
3. En **Database settings → SSL Configuration → Download Certificate**, descargá
   el certificado raíz del servidor. Desde `backend/`, creá la carpeta `certs/`
   y guardalo como `certs/supabase-ca.crt`. Si el panel cambia su ubicación, usá
   el enlace a Database settings de la documentación oficial citada abajo.
4. Desde `backend/`, copiá la plantilla **solo la primera vez**:

   ```powershell
   Copy-Item -LiteralPath .env.example -Destination .env
   ```

5. Editá `backend/.env` localmente. Completá `PGHOST`, `PGPORT`, `PGDATABASE`,
   `PGUSER` y `PGPASSWORD` con los datos anteriores. La contraseña es la de
   **PostgreSQL**, no la contraseña de tu cuenta ni una API key de Supabase.
   Conservá `PGSSLMODE=verify-full` y la ruta al certificado descargado.

El backend carga `backend/.env` automáticamente. Las variables de entorno del
proceso tienen prioridad y el archivo no se modifica. Las rutas de certificados
relativas parten de `backend/`. No se necesita una URL de conexión: al usar campos
separados, la contraseña no requiere codificación URL. La plantilla usa comillas
simples; si tu contraseña incluye comillas o barras invertidas, escapalas según
el formato de [python-dotenv](https://pypi.org/project/python-dotenv/).
No se interpolan expresiones `${...}` dentro de los valores.

La conexión verifica el certificado y el nombre del servidor mediante TLS
(`verify-full`). Si falla el certificado, comprobá el archivo y el host copiado;
no desactives SSL ni la verificación. Las instrucciones de conexión y descarga
del certificado están en la [documentación oficial de Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres).

**Credenciales:** `.env` y `backend/certs/` están excluidos de Git. La única plantilla
versionable es `.env.example`, que debe permanecer sin credenciales. No pongas
contraseñas en el frontend, variables `VITE_*`, capturas, URLs de prueba ni mensajes
de chat. No se necesita instalar el SDK de Supabase ni configurar claves
`anon`/`service_role`: FastAPI se conecta a PostgreSQL usando `psycopg`.

Después de completar o cambiar `.env`, reiniciá el backend con el comando de la
sección 1. No es necesario activar un entorno virtual.

### Verificar la conexión

Abrí <http://127.0.0.1:8001/api/health/database> o ejecutá en otra terminal:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8001/api/health/database
```

Si PostgreSQL responde realmente a `SELECT 1`, devuelve HTTP `200`:

```json
{"status":"ok","message":"Conexión con PostgreSQL verificada."}
```

La comprobación abre y cierra una conexión en modo de solo lectura. No crea tablas,
no ejecuta migraciones y no consulta datos de negocio. Limita la conexión mediante
`PGCONNECT_TIMEOUT` (cinco segundos por defecto) y la consulta a cinco segundos.

Si faltan datos o el certificado, devuelve HTTP `503` indicando configuración
incompleta o inválida. Si falla la conexión, devuelve `503` con un mensaje genérico,
sin exponer el error interno, usuario, host o contraseña. Revisá:

- Datos del Session pooler: especialmente host y usuario completo del pooler.
- Contraseña de PostgreSQL y certificado raíz correcto.
- Proyecto activo, acceso de red al puerto indicado y restricciones de red del proyecto.

El motivo técnico sanitizado aparece únicamente en la terminal de Uvicorn;
la API mantiene el mensaje genérico. No se imprimen contraseñas, host, usuario,
IP ni rutas del certificado. Si indica `FATAL: password authentication failed`,
el servidor fue alcanzado pero rechazó las credenciales. Para corregirlo:

1. Volvé a **Connect → Session pooler** del mismo proyecto y verificá `PGHOST`
   y `PGUSER` completos en tu `.env` local.
2. Usá en `PGPASSWORD` la contraseña vigente de PostgreSQL, sin codificación URL.
   Si no la conocés, restablecela desde **Database settings → Reset database password**
   en Supabase y esperá a que termine el cambio. Esa acción debe realizarla el titular
   del proyecto; puede afectar otros clientes que utilicen la contraseña anterior.
3. Reiniciá el backend. Si alguna variable `PG*` está definida en la terminal o
   configuración del IDE, tiene prioridad sobre el `.env`; actualizala también.
4. Volvé a consultar el endpoint. Si ejecutás el backend en el puerto `8001`, usá
   `http://127.0.0.1:8001/api/health/database`.

El reinicio para ese puerto, desde `backend/`, es:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

`/api/health` sigue comprobando solo FastAPI y funciona aunque PostgreSQL no esté
configurado. La pantalla inicial de HU-01 consulta `/api/auth/me`; la prueba de
conexión a PostgreSQL sigue siendo `/api/health/database`.

### Pruebas automatizadas sin Supabase

Desde `backend/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Para las pruebas de HU-01 instalar primero `requirements-dev.txt` con el mismo
Python del entorno virtual; agrega el cliente HTTP de pruebas.
Estas pruebas verifican configuración, prioridad de variables de entorno,
validación TLS, cierre de conexiones y errores sin filtraciones. Usan dobles de
prueba: no demuestran una conexión real a tu proyecto Supabase.

### Modelos y Alembic

Después de actualizar `requirements.txt`, volvé a instalar las dependencias con
el comando de la sección 1. Las pruebas también validan la estructura de los
15 modelos y compilan su DDL PostgreSQL sin conectarse a ninguna base.

Alembic está configurado en `backend/alembic.ini` y `backend/migrations/`.
La revisión `0001_der_inicial` incluye las 15 tablas, PK, FK, índices, CHECK,
triggers confirmados de pertenencia, cardinalidad diferida y RLS sin políticas
públicas. El SQL completo está en [docs/sql/0001_der_inicial.sql](docs/sql/0001_der_inicial.sql).
No ejecutar `create_all`, downgrade ni nuevas revisiones en Supabase sin revisión
y autorización.
El acceso online de Alembic está bloqueado por defecto y necesita aprobación
expresa antes de habilitarse. No se ejecuta ninguna migración al iniciar FastAPI.

Para volver a generar el SQL **sin ejecutarlo ni leer credenciales**, desde `backend/`:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
```

Las pruebas offline comprueban la revisión y sus metadatos. Las pruebas de
inserción, rechazo y concurrencia en PostgreSQL solo se activan con una base
local descartable: ver los requisitos y límites en el documento de etapa 2.
Sin esa base se omiten explícitamente; no se prueba contra Supabase.

## 3. Iniciar el frontend

En la segunda terminal, desde la raíz del repositorio:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Se utiliza `npm.cmd` para evitar restricciones de scripts de PowerShell.
En otras terminales podés usar `npm`.
`npm.cmd ci` instala las versiones registradas en `package-lock.json`.

Si npm informa `UNABLE_TO_VERIFY_LEAF_SIGNATURE` y utilizás Node.js 24 con un
certificado de red confiable instalado en Windows, podés usar el almacén de
certificados del sistema en esa terminal y repetir `npm.cmd ci`:

```powershell
$env:NODE_OPTIONS = '--use-system-ca'
```

Esto conserva la validación de certificados TLS.

Abrí <http://127.0.0.1:5173>. La pantalla muestra el formulario de inicio de sesión
y comprueba la sesión existente. Para usarla con PostgreSQL, seguir los pasos
de HU-01 enlazados al principio y preparar cuentas de demostración; las cuentas
usadas en las pruebas de integración se retiran mediante rollback.

El proxy local de Vite está definido en `frontend/vite.config.ts` y apunta a
`http://127.0.0.1:8001`, igual que el backend. El navegador usa un único origen.
Los puertos son fijos: si están
ocupados, detené el proceso correspondiente antes de iniciar los servidores.

## Comprobar la comunicación y los errores

1. Abrí <http://127.0.0.1:5173/api/health> para comprobar FastAPI y el proxy local.
2. Para verificar PostgreSQL, usá `/api/health/database` en el backend.
3. El backend incluye pruebas automatizadas de login, errores, sesión al recargar
   y cierre de sesión; se ejecutan con el comando de pruebas de la sección 2.
4. Revisá la pantalla en escritorio y en una ventana estrecha o emulación móvil.

Para verificar TypeScript y generar la compilación local del frontend:

```powershell
cd frontend
npm.cmd run build
```

Opcionalmente, `npm.cmd run preview` sirve esa compilación en
<http://127.0.0.1:4173>, con el mismo proxy local y el backend iniciado.
Esto no configura un despliegue.

Detené cada servidor con `Ctrl+C` en su terminal.

## Estructura

```text
frontend/
  src/
    app/          Pantalla y composición de la interfaz
    services/     Comunicación con la API
    styles/       Tokens y estilos compartidos
backend/
  app/
    main.py       Aplicación FastAPI
    api/          Endpoints técnicos de comprobación
    core/         Configuración mediante variables de entorno
    db/           Conexión PostgreSQL, engine y modelos del DER
  migrations/     Entorno Alembic, revisión inicial y SQL de triggers
  alembic.ini     Configuración sin credenciales
  tests/          Pruebas sin conexión real, incluyendo estructura del DER
  .env.example    Plantilla sin secretos
  requirements.txt
```

El DER vigente está en `docs/der/der.png`.
La tipografía usa Inter si está disponible y Arial como alternativa, sin descargas
de fuentes ni dependencias visuales adicionales.

Referencias de ejecución: [Vite](https://vite.dev/guide/) y
[FastAPI](https://fastapi.tiangolo.com/tutorial/first-steps/).
