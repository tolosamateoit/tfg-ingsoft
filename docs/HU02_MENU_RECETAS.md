# HU-02 — Gestión de menú, productos y recetas

Implementación acotada a la Tabla 9 de la tesis vigente y `ALCANCE_DEMO.md`.
Se conservan el DER, las tecnologías y la autenticación de HU-01. No se creó
ninguna migración ni se ejecutaron consultas o escrituras en Supabase en esta etapa.

## Funciones implementadas

- Personal y propietarios listan, crean y editan productos de su restaurante:
  nombre, precio de venta, costo unitario y estado activo/inactivo.
- La baja se realiza desactivando el producto; no se borran productos ni sus
  referencias en pedidos o predicciones. Los precios de detalles históricos no
  se reescriben al editar un producto.
- Consulta de insumos precargados del mismo restaurante, con nombre y unidad,
  para componer recetas. No incorpora gestión de stock ni CRUD de insumos.
- Consulta, edición y guardado completo de recetas: insumos únicos, cantidad
  positiva y unidad registrada de cada insumo, por una unidad del producto.
- React muestra el catálogo y los formularios únicamente a los roles autorizados.
  Hay estados de carga, confirmación, error, reintento y sesión vencida.

El menú que se administra aquí es el catálogo interno. La consulta de oferta por
clientes, carrito y confirmación corresponden a HU-03; no se anticiparon esas
funciones. Tampoco hay imágenes, categorías, descripciones, impuestos u otras
columnas ausentes del DER.

## API y seguridad

Todas las rutas están bajo `/api/restaurantes/{id_restaurante}`:

| Método | Ruta relativa | Función |
| --- | --- | --- |
| GET | `/productos` | Lista productos activos e inactivos del restaurante autorizado. |
| POST | `/productos` | Crea producto asociado en el servidor al restaurante autorizado. |
| PUT | `/productos/{id_producto}` | Edita los campos del producto, sin permitir reasignarlo de restaurante. |
| GET | `/insumos` | Lista insumos del restaurante; no devuelve stock ni costos. |
| GET | `/productos/{id_producto}/receta` | Consulta componentes, cantidades y unidades de la receta. |
| PUT | `/productos/{id_producto}/receta` | Reemplaza atómicamente los componentes de la receta. |

Se reutilizan la sesión, CSRF y dependencias de rol/pertenencia de HU-01.
Cada ruta exige `personal` o `propietario` vinculado al restaurante seleccionado.
Cliente, repartidor y administrador de plataforma no obtienen acceso a costos,
insumos o recetas. Conocer un ID ajeno no permite consultarlo ni modificarlo.
No se aceptan atributos extra como `id_restaurante` en el cuerpo del producto.
Las consultas filtran por restaurante y la lectura de receta usa joins, sin
una consulta por cada componente.

Ejemplo de producto (crear o editar):

```json
{"nombre":"Pizza", "precio":"6500.00", "costo_unitario":"620.00", "activo":true}
```

Ejemplo de receta:

```json
{"detalles":[{"id_insumo":1,"cantidad":"0.200000","unidad":"kg"}]}
```

Los IDs de ambos ejemplos son ilustrativos: los insumos deben existir en el
restaurante autorizado. Los PUT de producto envían todos sus campos. Los PUT de
receta envían la lista completa; una lista vacía deja el producto sin receta,
conforme a la cardinalidad 0..N del DER.

## Validaciones y consistencia

- Nombre sin espacios exteriores, de 1 a 150 caracteres.
- Importes finitos y no negativos, con precisión NUMERIC(18,2); se rechaza la
  precisión excedente en vez de redondearla silenciosamente. Precio y costo son
  campos distintos, de edición explícita; no se calcula automáticamente el costo
  del producto al guardar la receta.
- Los importes viajan como cadenas decimales con dos cifras. La UI los presenta
  sin convertir el importe completo a punto flotante, incluso en el límite de
  precisión admitido por PostgreSQL.
- Cantidades positivas y finitas, con precisión NUMERIC(18,6). No se repite el
  mismo insumo en una receta. Límite técnico de 100 componentes por solicitud.
- Se valida en FastAPI la pertenencia de **todos** los insumos antes de reemplazar
  la receta. Una referencia inválida, unidad incompatible o error de integridad
  conserva la receta anterior mediante rollback.
- Se utiliza la unidad del insumo. No hay conversión entre kg/g, l/ml u otras
  unidades, ya que no está definida en el alcance; la interfaz muestra la unidad
  correspondiente al seleccionar cada insumo.
- El guardado adquiere el mismo advisory lock de relaciones utilizado por 0001,
  antes de los locks de filas, y bloquea el producto y los insumos implicados.
  Los guardados concurrentes quedan serializados; cada PUT reemplaza una receta
  completa y el último guardado confirmado prevalece.
- Guardar recetas o desactivar productos no consume stock ni crea movimientos.
  Esas operaciones pertenecen a HU-04.

## Catálogo de demostración

Los insumos se precargan, según el alcance aprobado. Para generar un catálogo
pequeño identificado como sintético para un restaurante existente, desde backend:

```powershell
.\.venv\Scripts\python.exe -m app.menu.demo --restaurant-id ID_REAL --output demo-menu.sql
```

Reemplazar `ID_REAL` por el restaurante de demostración elegido. El generador
es offline: no lee credenciales, no abre conexiones y no ejecuta SQL. Prepara
3 insumos, 2 productos y sus recetas en una transacción; evita sobrescribir el
archivo de salida y rechaza una carga duplicada en el restaurante. La base asigna
los IDs. No modifica usuarios, roles o restaurantes existentes. Los precios,
costos y existencias de ese archivo son **datos sintéticos**, no datos reales.
El SQL fue probado en PostgreSQL local descartable; no se aplicó en Supabase.

Para uso normal, iniciar `app.main:app` y Vite según el README, con una cuenta de
personal o propietario de HU-01. El gestor de menú aparece después del login.
No se añadieron dependencias ni variables de entorno para HU-02.

## Pruebas y recorrido local

Suite completa con PostgreSQL local descartable y Docker iniciado, desde backend:

```powershell
.\.venv\Scripts\python.exe -m tests.run_postgresql_local
```

La suite incluye regresión de HU-01, validaciones y aislamiento de HU-02,
persistencia decimal exacta en PostgreSQL, reemplazo/limpieza de recetas,
rollback ante errores, concurrencia, conservación del stock y del historial,
consultas sin N+1 y carga sintética sin sobrescritura. El contenedor se elimina
al finalizar. No usa `.env` ni la conexión de Supabase.

Resultado final: **117 pruebas correctas, sin omisiones**, de las cuales 48 usan
PostgreSQL 17.11 real. `npm.cmd run build` pasó con TypeScript y Vite. No se
presentan estas pruebas locales como una validación de HU-02 en Supabase.

Para repetir QA de interfaz sin PostgreSQL, desde backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn tests.preview_menu:app --host 127.0.0.1 --port 8001
```

En otra terminal, desde frontend, `npm.cmd run dev`. Ingresar en
`http://127.0.0.1:5173` con `u1@test.invalid` (personal) o `u7@test.invalid`
(propietario), clave sintética `Frase demo segura 42`. `u2@test.invalid` pertenece
al segundo restaurante y `u3@test.invalid` es cliente sin controles de gestión.
Este servidor usa SQLite temporal y simula únicamente advisory locks; no se debe
desplegar. Se retiran los datos al detenerlo. La certificación de integridad,
concurrencia y precisión decimal se hace con PostgreSQL, no con SQLite.

Recorrido verificado en navegador: crear producto, editar precio y estado,
agregar insumos con cantidades/unidades, guardar receta, recargar y comprobar
persistencia, cerrar sesión y verificar que un cliente no vea gestión. Revisión
en 1280×1000 y 390×844 sin desbordamiento horizontal. Se corrigió el manejo de
conexiones paralelas del servidor de QA y la presentación de importes recibidos
en notación científica. Un error al cargar una receta impide guardarla hasta
que se consiga leerla, para evitar reemplazarla por una lista vacía por accidente.

No hay bloqueos del esquema. Quedan la precarga autorizada de datos de demo y
la comprobación del recorrido HU-02 en el entorno desplegado; no se usó Supabase
ni se repitió el despliegue público en esta etapa.
