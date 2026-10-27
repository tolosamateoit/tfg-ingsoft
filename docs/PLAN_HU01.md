# Etapa 3 — HU-01: plan para aprobación

Estado: plan y dos tablas técnicas aprobados por el autor. Implementación
preparada y migración aplicada en Supabase mediante Alembic con autorización.
Este documento conserva el plan acordado; ver `HU01_AUTENTICACION.md` para el
resultado y los pasos de ejecución.

## Referencias verificadas

- `AGENTS.md`, `CONTEXTO_TESIS.md`, `ALCANCE_DEMO.md` y `DESIGN.md`.
- [Tesis vigente](https://docs.google.com/document/d/18FeunTyDUEuLoCRtkokky5dlJ04Bn5tbNH1kRvNLQZk/edit?tab=t.0),
  Tabla 8 (HU-01) y sección Seguridad, leídas el 26/10/2026.
- `docs/der/der.png`, modelos y revisión inicial de la etapa 2.

El autor confirmó que la migración inicial está aplicada en Supabase y que sus
pruebas de integridad y comprobaciones manuales pasaron. No se repitieron esas
operaciones ni se accedió a Supabase durante esta revisión. Los documentos de
etapa 2 conservan afirmaciones del momento en que fueron escritos.

HU-01 exige que un usuario activo pueda iniciar sesión y acceder únicamente a
funciones autorizadas; que se rechacen acciones sin permiso; y que conocer el
identificador de un recurso ajeno no permita consultar ni modificarlo.

## Alcance de la implementación

1. Login con correo y contraseña; logout y consulta de sesión actual.
2. Argon2id con sal individual en `usuario.hash_contrasena`, sin cambiar esa
   columna. Incorporar `argon2-cffi`, biblioteca Python necesaria para el
   requisito solicitado. Al preparar contraseñas nuevas, validar los 15–20
   caracteres previstos por la tesis, admitir espacios y frases y rechazar una
   lista local documentada de claves comunes/conocidas. Esa lista no implica
   comprobar todas las filtraciones existentes.
3. Sesión con token aleatorio de 256 bits; guardar solamente su hash SHA-256.
   Cookie HttpOnly, SameSite y Secure en HTTPS; excepción explícita únicamente
   para desarrollo local en HTTP. Caducidad absoluta propuesta: 8 horas.
   Revocación del lado servidor al salir, sin guardar tokens en localStorage.
   Proteger solicitudes mutables contra CSRF y no registrar credenciales ni
   tokens. Mantener el mismo origen mediante el proxy local de Vite, corrigiendo
   su destino al puerto 8001 que usa el README.
4. En cada solicitud protegida, consultar usuario activo y permisos vigentes en
   el backend. No aceptar rol o restaurante declarados por el frontend como
   autorización. Denegar roles desconocidos por defecto.
5. Tras 5 fallos consecutivos por correo normalizado, impedir el login durante
   15 minutos, incluso con contraseña correcta. Un éxito reinicia el contador;
   después del plazo comienza una nueva secuencia. Los intentos durante el
   bloqueo no extienden su duración. Actualizar el contador de forma atómica
   para soportar solicitudes concurrentes.
6. Usar respuestas genéricas para correo inexistente, contraseña incorrecta,
   usuario inactivo y bloqueo. Tratar correos inexistentes con la misma política
   de intentos y una verificación de contraseña ficticia para reducir diferencias
   observables, sin afirmar tiempos de respuesta idénticos.
7. React: formulario con etiquetas de correo y contraseña, estado de envío y
   error genérico; al autenticar, mostrar identidad, rol, ámbito autorizado y
   botón para cerrar sesión. Reutilizar tokens CSS existentes. Sin navegación a
   funciones todavía no implementadas ni diseño visual definitivo.
8. Cuentas de prueba precargadas, sin registro público. Preparar una forma
   explícita y documentada de generar hashes y cargar usuarios sintéticos con
   sus relaciones obligatorias; no ejecutarla automáticamente contra Supabase.

### Roles y pertenencia

| Perfil de la tesis | Regla que debe garantizar la base de autorización |
| --- | --- |
| Cliente | Acceso a recursos propios; puede comprar en distintos restaurantes. No exigir restaurante fijo al cliente. |
| Personal del restaurante | Solo operaciones permitidas en su restaurante. |
| Propietario | Permisos operativos y de propietario, limitados a su restaurante. |
| Repartidor | Restaurante por `usuario.id_restaurante`; acceso solo a entregas asignadas y datos necesarios. |
| Administrador de la plataforma | Sin bypass global sobre datos operativos o sensibles. El soporte de HU-11 no se implementa aquí. |

Preparar dependencias y comprobaciones reutilizables de usuario, rol,
restaurante, titularidad del cliente y asignación al repartidor. Verificar
pertenencia mediante las relaciones existentes y consultas parametrizadas.
No implementar CRUD de menú, pedidos, entregas, stock o indicadores para
demostrar permisos: las pruebas podrán montar rutas de prueba sobre estas
dependencias sin publicar funcionalidades de otras HU.

### Recuperación de contraseña

`ALCANCE_DEMO.md` excluye expresamente la recuperación de contraseña en esta
primera demo. Por eso, HU-01 de esta entrega no incluirá envío de correo, tokens
de recuperación ni un formulario que afirme haber enviado un mensaje. El login
indicará que la recuperación por correo no está disponible en el prototipo.
La recuperación por correo descrita en la tesis queda pendiente del sistema
completo; no se presentará como implementada.

## Cambios de base de datos que requieren aprobación

El DER y las 15 tablas existentes no tienen almacenamiento de sesiones ni de
intentos/bloqueos. Guardarlos en memoria perdería el estado al reiniciar y no lo
compartiría entre procesos. Se propone una migración nueva, posterior a
`0001_der_inicial`, con estas dos tablas técnicas en PostgreSQL:

| Tabla propuesta | Campos propuestos | Motivo |
| --- | --- | --- |
| `auth_estado_acceso` | `clave_correo TEXT PRIMARY KEY`, `intentos_fallidos INTEGER NOT NULL`, `bloqueado_hasta TIMESTAMPTZ NULL`, `actualizado_en TIMESTAMPTZ NOT NULL` | Persistir contador y bloqueo por correo normalizado, también para correos que no existen. `clave_correo` será el SHA-256 del correo normalizado. No es un hash de contraseña ni garantiza anonimato del correo. |
| `auth_sesion` | `token_hash TEXT PRIMARY KEY`, `id_usuario INTEGER NOT NULL REFERENCES usuario(id_usuario)`, `creada_en TIMESTAMPTZ NOT NULL`, `expira_en TIMESTAMPTZ NOT NULL` | Validar caducidad y revocar sesión al cerrar sesión. El token original solo viaja en la cookie. |

Restricciones propuestas: contador entre 0 y 5; hash de 64 caracteres
hexadecimales; vencimiento posterior a creación; FK sin borrado en cascada.
Índices en `auth_sesion.id_usuario` y fechas usadas para depuración de registros
vencidos. RLS habilitada sin políticas públicas, manteniendo el acceso a través
de FastAPI y no mediante la Data API de Supabase. Depurar estados antiguos sin
bloqueos vigentes y sesiones caducadas mediante una operación documentada.

Estas tablas constituyen una ampliación técnica del esquema y requieren tu
aprobación aunque no cambien las entidades de negocio. No se alterarán las
tablas actuales, sus columnas o relaciones, la imagen del DER ni la migración
inicial ya aplicada. La migración nueva y su SQL completo se prepararán para
revisión; aplicarlos en Supabase será una acción posterior y explícita.

## Orden y validación

Una vez aprobado este plan y la ampliación técnica:

1. Implementar el módulo de autenticación y su migración independiente.
2. Implementar las dependencias de autorización y aislamiento.
3. Conectar la pantalla básica de React y documentar configuración y cuentas.
4. Ejecutar pruebas y entregar resultados reales, indicando omisiones.

Pruebas previstas:

- Argon2id: sal individual, contraseña válida/incorrecta, hash inválido y
  validación al preparar claves nuevas.
- Login: usuario activo, inactivo, correo inexistente y entradas inválidas.
- Bloqueo: fallos 1–4, quinto fallo, contraseña correcta durante el bloqueo,
  vencimiento exacto, reinicio por éxito, persistencia y concurrencia.
- Sesiones: cookies, expiración, token alterado, logout, usuario desactivado y
  cambio de rol/pertenencia durante una sesión; errores sin datos sensibles.
- Autorización: todos los roles y denegación por defecto; falta de sesión,
  permiso insuficiente y administrador sin acceso operativo global.
- Aislamiento: dos restaurantes, IDs conocidos ajenos, cliente distinto y
  repartidor distinto; pruebas sobre dependencias reales de FastAPI.
- Integración PostgreSQL solo en base local descartable configurada
  explícitamente. Si no está disponible, informar las omisiones, sin confundir
  pruebas con dobles o una base en memoria con integración PostgreSQL.
- Compilación TypeScript y frontend; revisión del login en escritorio y móvil.

Base verificada antes de cambios: `python -m unittest discover -s tests -v`
desde el entorno virtual de `backend`: **33 pruebas, 25 correctas y 8 omitidas**
por falta de PostgreSQL local descartable. No son pruebas de HU-01, que aún no
está implementada.

Referencias técnicas: [argon2-cffi](https://argon2-cffi.readthedocs.io/en/stable/howto.html)
y [gestión de sesiones de OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
