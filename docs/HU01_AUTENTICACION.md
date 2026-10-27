# HU-01 — Autenticación y control de acceso

Estado: **migración 0002 aplicada en Supabase mediante Alembic con autorización**.
El autor confirmó que `0001_der_inicial` está aplicada y verificada. La imagen
del DER, las 15 tablas de negocio y la revisión 0001 no se modificaron.

## SQL para revisión

Archivo completo: [sql/0002_hu01_auth.sql](sql/0002_hu01_auth.sql).
Revisión Alembic: `backend/migrations/versions/0002_hu01_auth.py`, dependiente de
`0001_der_inicial`. El SQL incluye BEGIN/COMMIT y el avance de `alembic_version`.
No crea de nuevo las tablas de negocio ni ejecuta carga de usuarios.

| Tabla | Relación y restricciones |
| --- | --- |
| `auth_estado_acceso` | PK `clave_correo`: SHA-256 del correo normalizado, 64 caracteres hexadecimales minúsculos. Contador obligatorio entre 0 y 5. `actualizado_en` obligatorio; `bloqueado_hasta` opcional, ambos con zona horaria. Sin FK a usuario: permite tratar también correos inexistentes sin enumerar cuentas. |
| `auth_sesion` | PK `token_hash`: SHA-256 del token aleatorio, 64 caracteres hexadecimales minúsculos. FK obligatoria a `usuario.id_usuario`, con RESTRICT al borrar o cambiar la PK del usuario. Creación y vencimiento obligatorios con zona horaria; vencimiento posterior a creación. Un usuario puede tener varias sesiones. |

Índices: última actualización del estado de acceso; usuario y vencimiento de
sesión. Las PK ya indexan ambos hashes. RLS habilitada sin políticas públicas y
privilegios de PUBLIC, anon, authenticated y service_role revocados en ambas tablas. FastAPI usa la conexión privada
existente; no se emplea Supabase Auth ni se exponen estas tablas desde React.
La conexión debe conservar el acceso del backend a las tablas bajo ese modelo.

El CHECK del contador valida su rango; la regla de cinco fallos y quince minutos
la implementa FastAPI. Un advisory lock transaccional por correo serializa las
lecturas y escrituras incluso antes de que exista su fila. Este mecanismo requiere
el aislamiento READ COMMITTED predeterminado de PostgreSQL.

Generación offline reproducible desde `backend/`, sin leer credenciales ni conectar:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade 0001_der_inicial:0002_hu01_auth --sql
```

Se ejecutó `upgrade` online a `0002_hu01_auth` con autorización, utilizando la
conexión privada existente y la revisión de esquema previa. En la misma
transacción se ejecutó [hu01_permisos_aplicacion.sql](sql/hu01_permisos_aplicacion.sql):
revocación de privilegios de PUBLIC, anon, authenticated y service_role solo en
las 15 tablas de negocio y alembic_version. La propia 0002 restringe las 2 tablas
nuevas. Se conservó postgres y no se tocaron otros esquemas ni permisos por
defecto. No se ejecutó un downgrade en Supabase. Los encabezados del SQL generado
y de la revisión conservan el estado histórico de su preparación; el estado de
aplicación actual es el indicado aquí y en alembic_version.

## Configuración e inicio

Desde `backend/`, actualizar dependencias:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Completar **solo estas variables adicionales** en el `.env` local existente,
sin sobrescribir las credenciales PG ya configuradas:

```dotenv
AUTH_COOKIE_SECURE=false
AUTH_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173
```

No incluir una barra final en los orígenes. Para producción, usar
`AUTH_COOKIE_SECURE=true` y orígenes HTTPS exactos. Si se desactiva Secure, la
configuración solo acepta hosts loopback. Los valores ausentes/incorrectos
rechazan la autenticación de forma cerrada con 503.

El frontend usa `/api`, con proxy local a `http://127.0.0.1:8001`. En un despliegue
futuro debe conservarse el mismo origen del navegador mediante un proxy de `/api`
al backend; todavía no se configuró ese despliegue ni se habilitó CORS público.

Con las migraciones ya aplicadas y después de precargar cuentas, iniciar:

```powershell
# Terminal backend/
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# Otra terminal, frontend/
npm.cmd run dev
```

Abrir `http://127.0.0.1:5173`. La autenticación requiere usuarios activos con
hashes Argon2id. Las cuentas sintéticas de las pruebas remotas se retiran con
rollback y no quedan disponibles como usuarios de demostración. Iniciar FastAPI
no aplica migraciones.

## Cuentas sintéticas

Generador offline, desde `backend/`:

```powershell
.\.venv\Scripts\python.exe -m app.auth.accounts --output demo-auth.sql
```

Solicita sin eco una contraseña y su confirmación. Genera SQL con dos restaurantes
y nueve usuarios identificados como sintéticos, con una sal distinta por usuario:

| Correos `@demo.invalid` | Rol / restaurante |
| --- | --- |
| `personal1`, `personal2` | Personal de restaurantes sintéticos 1 y 2 respectivamente |
| `propietario1`, `propietario2` | Propietarios de restaurantes sintéticos 1 y 2 respectivamente |
| `repartidor1`, `repartidor2` | Repartidores de restaurantes sintéticos 1 y 2, con perfil repartidor |
| `cliente1`, `cliente2` | Clientes sin restaurante fijo, con perfil cliente |
| `administrador` | Administrador de plataforma, sin permisos operativos globales |

Los IDs reales los asigna PostgreSQL; no se fijan IDs ni se reutilizan restaurantes
existentes. La transacción rechaza cuentas sintéticas ya existentes y no las
sobrescribe. El generador no abre conexiones ni ejecuta SQL. Su archivo contiene
hashes y debe mantenerse privado: `backend/demo-auth*.sql` está excluido de Git.
Revisar esa carga por separado antes de ejecutarla; no se ha ejecutado ni se
certifica su integración PostgreSQL en esta entrega.

Las cuentas se precargan con correo en minúsculas y sin espacios exteriores.
Login normaliza igual y usa la unicidad/indexación existente de `usuario.correo`;
no se creó un índice funcional ni se cambió la restricción actual. No convertir
cuentas antiguas automáticamente: revisar primero posibles duplicados por mayúsculas.

La política de claves nuevas exige 15–20 caracteres, conserva espacios y no exige
combinaciones obligatorias. La lista de claves rechazadas es local y pequeña,
definida en `security.py`; no verifica todas las filtraciones existentes.

## Endpoints y permisos

| Método/ruta | Comportamiento |
| --- | --- |
| `POST /api/auth/login` | JSON `correo`, `contrasena`; usuario activo y rol reconocido. Crea cookie HttpOnly con token aleatorio de 256 bits. Solo se persiste su SHA-256. |
| `GET /api/auth/me` | Sesión válida; devuelve ID, nombre, correo, rol y restaurante vigentes, nunca hash ni token. |
| `POST /api/auth/logout` | Revoca la sesión en DB y elimina la cookie. |

Sesiones de 8 horas de duración absoluta, SameSite=Lax y Secure en producción.
Cada solicitud protegida consulta sesión, actividad, rol y restaurante actuales;
desactivar al usuario corta su acceso aunque conserve la cookie. Las respuestas
de API se marcan no-store. No se guardan tokens en localStorage.

Las solicitudes mutables requieren `Origin` exacto de la lista permitida y el
encabezado no simple `X-CSRF-Protection: 1`. React lo agrega automáticamente.
Los clientes de prueba de API deben enviarlos también; un envío directo desde
Swagger sin esos encabezados se rechaza. No se configuran orígenes comodín ni
CORS que permita enviar el encabezado desde sitios ajenos.

Los fallos para contraseña incorrecta, correo inexistente, usuario inactivo,
rol inválido o bloqueo tienen el mismo mensaje y estado 401. El quinto fallo
bloquea 15 minutos incluso con contraseña correcta; nuevos intentos no prolongan
el plazo. Al vencer empieza una nueva secuencia; un éxito reinicia el contador.
El estado persiste en PostgreSQL, no en un diccionario del proceso. El hash del
correo no garantiza anonimato. Se utiliza verificación ficticia cuando no hay un
hash Argon2id válido disponible, sin prometer tiempos idénticos.

Dependencias reutilizables en `app/auth/dependencies.py`:

- `current_user` y `require_roles`: sesión y lista explícita de roles; desconocidos
  se rechazan por defecto. Valores internos: `cliente`, `personal`, `propietario`,
  `repartidor`, `administrador_plataforma`.
- `require_restaurant`: rol permitido y restaurante asignado coincidente. El ID
  enviado por el cliente es un selector, nunca la prueba de autorización.
- `own_client` y `accessible_order`: titularidad de cliente y/o restaurante del
  personal. El cliente puede consultar sus propios pedidos en varios restaurantes.
- `assigned_delivery`: solo repartidor asignado y pedido de su restaurante.

Las rutas de negocio futuras deben usar estas dependencias además de sus permisos
por acción y validaciones propias. No se publicaron CRUD de otras HU: las rutas
que ejercitan dependencias solo se montan en la aplicación de pruebas.

La recuperación de contraseña por correo y el registro público permanecen fuera
del alcance de esta demo; no existen endpoints que simulen envíos.

## Pruebas ejecutadas y límites

Desde `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Validación con PostgreSQL local, realizada el 26/10/2026: **83 pruebas correctas,
ninguna omitida**, incluidas las 11 anteriormente pendientes. Para repetirla con
Docker iniciado, desde `backend/`:

```powershell
.\.venv\Scripts\python.exe -m tests.run_postgresql_local
```

El runner inicia la imagen oficial `postgres:17` en un contenedor con nombre único,
puerto dinámico exclusivamente en `127.0.0.1`, contraseña aleatoria y almacenamiento
tmpfs descartable. No lee `.env` ni utiliza la configuración de Supabase. Al
finalizar detiene únicamente ese contenedor, que se elimina automáticamente.
La ejecución verificada usó PostgreSQL 17.11, imagen digest
`sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04658c28b44e2408fe`.

Alembic aplica realmente 0001 y 0002 sobre `tfg_test_hu01`, con las conexiones
locales suministradas por los tests. La revisión y el catálogo confirman 15 tablas
del DER, 2 técnicas y `alembic_version`, con las PK, FK, CHECK, índices y RLS.
Las pruebas ejercitan también el downgrade local. Los fixtures se corrigieron
para incluir detalles obligatorios de pedidos y retirar su propia tabla de
versión vacía al finalizar, permitiendo repetir suites en la misma base descartable.
No se cambió el DER ni la lógica de negocio.

Se conservan las pruebas rápidas SQLite, y se repiten los 16 recorridos de API
contra PostgreSQL real con `get_db` de producción y un engine exclusivamente
local, sin simular advisory locks. Cubren login, logout, token revocado/reutilizado,
caducidad, usuario desactivado, quinto fallo, bloqueo de 15 minutos, CSRF,
cambios de permisos y aislamiento entre restaurantes, clientes y repartidores.
Los límites temporales se verifican con reloj controlado; no se espera 15 minutos.
Las pruebas de concurrencia ejecutan escrituras en conexiones PostgreSQL distintas.

Se verificó que `postgres`, propietario de las tablas pero **sin superusuario ni
BYPASSRLS**, conserva SELECT/INSERT/UPDATE/DELETE y permite operar a FastAPI.
Antes de migrar se conceden permisos por defecto a los roles de API y también a
PUBLIC para comprobar que las revocaciones los eliminan. Después se comprueba
ausencia de permisos de PUBLIC en ACL y de los tres roles de API, incluido
TRUNCATE y MAINTAIN, y rechazo real de SELECT/TRUNCATE al ejecutar como esos roles,
incluso cuando `service_role` tiene BYPASSRLS.

Para usar una base local propia, las suites opt-in conservan la validación de
`TFG_TEST_POSTGRES_DSN`: base vacía y descartable `tfg_test_*` en loopback. Necesita
los roles `anon`, `authenticated` y `service_role`; las comprobaciones de permisos
necesitan además la preparación que realiza el runner. Sin esa configuración las
30 pruebas PostgreSQL se omiten expresamente. No apuntar a una base con datos
que deban conservarse. El runner es la forma reproducible recomendada.

Esta ejecución no valida el TLS ni los privilegios efectivos de un proyecto
Supabase: no se conectó a él ni se ejecutaron allí consultas o migraciones.

### Integración posterior con Supabase

Con autorización del autor se revisó Supabase en modo de solo lectura y se
comprobó: PostgreSQL 17.11, TLS verificado, revisión inicial aplicada, 15 tablas
de negocio vacías y sin diferencias inesperadas respecto de los modelos, ninguna
conexión activa ajena ni vistas/políticas propias dependientes del acceso por
los roles de API. El código usa exclusivamente la conexión privada postgres.
Sobre esa base se restringieron los permisos de la aplicación y se aplicó 0002.

La verificación posterior confirmó `0002_hu01_auth`, ausencia de diferencias
de esquema, RLS habilitada sin políticas públicas, propiedad postgres y ausencia
de privilegios de PUBLIC y los tres roles de API sobre las tablas de aplicación.
Postgres conserva el acceso necesario. No se cambiaron columnas, relaciones del
DER ni registros existentes. Los grants por defecto de Supabase permanecen como
estaban: las migraciones futuras deben restringir explícitamente tablas internas.

Prueba remota explícita, no incluida en unittest discover:

```powershell
# Solo con autorización para ejecutar pruebas en la conexión configurada.
.\.venv\Scripts\python.exe -m tests.run_supabase_hu01 --run
```

Este ejecutor no migra ni elimina tablas. Crea usuarios, restaurantes y recursos
sintéticos con correos UUID e IDs negativos aleatorios, sin avanzar las secuencias.
Todos los cambios quedan dentro de una transacción exterior que nunca confirma;
los commits de las sesiones de prueba solo liberan savepoints. Las peticiones
ASGI usan los handlers reales de HU-01 y consultas reales contra Supabase por TLS.
La dependencia de sesión se adapta únicamente para conservar ese rollback exterior.
No se despliegan las rutas auxiliares de autorización en la API de producción.

Resultado final: 11 pruebas remotas correctas. Se verificaron CHECK/FK, login,
logout y rechazo del token reutilizado, bloqueo de 5 fallos durante 15 minutos,
reinicio por éxito, revocación de servidor, usuario desactivado, CSRF/caducidad,
respuestas sin enumerar cuentas y aislamiento de restaurantes/clientes/repartidores.
Los límites temporales usan reloj controlado; las escrituras remotas son reales.
El primer pase identificó un error en el reloj del ejecutor de pruebas, que se
corrigió antes de repetir la suite. No requirió cambios al código de autenticación.
El rollback final verifica que los usuarios temporales desaparecieron y que los
conteos de las 17 tablas permanecen iguales a los iniciales.

También pasaron 30 pruebas locales de autenticación, migración offline y seguridad
de configuración. La integración en Supabase no equivale a la publicación web:
quedan la carga explícita de cuentas de demo y, para acceso público, el alojamiento
React/FastAPI con HTTPS, proxy de /api, Secure=true y orígenes HTTPS exactos.

`npm.cmd run build` pasó (TypeScript + Vite). QA en navegador contra el servidor
de pruebas SQLite: error por clave incorrecta, login válido, identidad/rol/ámbito,
sesión al recargar y logout. Revisado en 390×844 y 1280×900 sin desbordamiento
horizontal. Los datos usados son sintéticos; no son una prueba de Supabase.

Para repetir ese QA sin PostgreSQL: iniciar el servidor de prueba con
`python -m uvicorn tests.preview_auth:app --host 127.0.0.1 --port 8001` desde el
entorno virtual de backend y Vite desde frontend. Usuario `u1@test.invalid`,
clave sintética `Frase demo segura 42`. El servidor usa memoria y simula el lock,
no importa configuración PG ni se debe desplegar. Detenerlo al terminar y volver
a `app.main:app` para usar PostgreSQL. No ejecutar ambos en el mismo puerto.

## Mantenimiento manual posterior

Una vez aprobada y aplicada la migración, se pueden depurar sesiones vencidas y
estados antiguos sin bloqueo vigente mediante estas consultas revisables. No se
ejecutaron y no se agregó una tarea programada:

```sql
DELETE FROM public.auth_sesion WHERE expira_en <= now();
DELETE FROM public.auth_estado_acceso
WHERE actualizado_en < now() - interval '1 day'
  AND (bloqueado_hasta IS NULL OR bloqueado_hasta <= now());
```

La autorización sigue siendo responsabilidad de FastAPI; los CHECK y RLS no
reemplazan la pertenencia ni los permisos por acción. No se afirma que el resto
de las historias o el despliegue estén implementados.
