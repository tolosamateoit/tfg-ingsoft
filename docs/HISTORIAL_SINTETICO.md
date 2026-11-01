# Historial sintético de 90 días

El módulo `backend/app/demo_history` importa operaciones ficticias reproducibles
en las tablas existentes. No altera el DER, la interfaz ni los motores.
No crea tablas ni aplica migraciones. Requiere `0003_producto_presentacion`.

## Identidad y alcance

- Crea un restaurante independiente llamado **Rotisería del Pueblo**. El nombre
  puede coincidir con el restaurante anterior de la demo: nunca se lo selecciona
  por nombre ni se lo modifica.
- La identidad del dataset es la cuenta `lucia@hist90.oliva.invalid`, su
  restaurante y la marca `[OLIVA-HIST90:v1]` en el horario. Todas las cuentas,
  clientes, productos, recetas, insumos y repartidores de la carga son exclusivos.
- Los pedidos conservan semilla, corte, huella del plan e índice en
  `referencia_local`. Eventos y movimientos identifican su origen sintético en
  `detalle`/`motivo`. Los nombres visibles de personas y productos son naturales.
- Las credenciales son aleatorias por cuenta, con Argon2id y sal individual.
  Se entregan en un archivo local privado, nunca en consola ni en Git.

## Ejecución

Desde `backend/`, con el entorno y certificado TLS de Supabase ya configurados:

```powershell
# Plan sin conexiones ni escrituras.
.\.venv\Scripts\python.exe -m app.demo_history plan --as-of 2026-10-31 --seed 20261031

# Revisar migración e identidad reservada, en una transacción de solo lectura.
.\.venv\Scripts\python.exe -m app.demo_history check --as-of 2026-10-31

# Cargar, únicamente después de revisar/probar el plan.
.\.venv\Scripts\python.exe -m app.demo_history load --as-of 2026-10-31 --seed 20261031 --execute

# Verificación posterior sin escribir.
.\.venv\Scripts\python.exe -m app.demo_history validate --as-of 2026-10-31 --seed 20261031
```

`load` sin `--execute` equivale al plan offline. Sin `--as-of` se toma la fecha
actual de Buenos Aires; para repetir exactamente la carga hay que conservar
explícitamente **la fecha de corte y la semilla**.

El período es `[corte − 90 días, corte − 1 día]`, en Buenos Aires. Para este
ejemplo abarca **02/08/2026–30/10/2026**, inclusive. Se persisten instantes UTC;
el motor actual continúa agrupando por UTC. Los últimos eventos nocturnos pueden
caer en la madrugada UTC del día siguiente, pero siempre antes del corte local.

## Respaldo y reinicio

Los respaldos y manifiestos se guardan en `.tools/history-demo/` (ignorado por
Git). Se puede elegir otra carpeta con `--output-dir`.

Si existe el dataset, se verifica y escribe un respaldo completo **antes de
cualquier reinicio**, incluyendo catálogo, cuentas, historial y resultados
analíticos. El JSON conserva tipos de fechas y decimales, su huella y las filas
por tabla. Contiene hashes y posiblemente sesiones: conservarlo como archivo
privado. No es un respaldo global de Supabase ni se restaura automáticamente.
Ante una falla de escritura o verificación del respaldo, se rechaza el reinicio.

Repetir `load` con iguales parámetros es idempotente: valida y devuelve
`action: unchanged`; no duplica ni cambia el historial. Para recrearlo:

```powershell
# Sustituir 123 por el restaurant_id informado en el manifiesto.
.\.venv\Scripts\python.exe -m app.demo_history load --as-of 2026-10-31 --seed 20261031 --execute --reset --restaurant-id 123
```

El reinicio conserva el restaurante, catálogo, usuarios y contraseñas. Recrea
solo sus operaciones generadas, movimientos y disponibilidades históricas.
Los ID de operaciones cambian por las secuencias PostgreSQL; su contenido
funcional, cantidades y tiempos se reproducen.

Si ya hay predicciones o alertas calculadas por la aplicación, el reinicio se
rechaza por defecto. Solo para retirarlas deliberadamente, después de revisar
el respaldo, agregar `--clear-derived`. Ese permiso afecta exclusivamente al
restaurante dedicado. Una carga normal nunca crea, cambia ni elimina esos
resultados.

Si aparecen pedidos/eventos/movimientos sin la marca del generador, cuentas o
catálogo ajenos, o relaciones con otros restaurantes, **el reinicio se rechaza**.
No existe una opción de borrado forzado. Los experimentos manuales posteriores
deben revisarse antes de retirar datos que ya no puede atribuirse al generador.

La transacción valida sus FK diferidas antes del commit y compara una huella de
los registros externos antes/después. Si hay diferencias, se revierte la carga,
sin intentar restaurar ni modificar registros de otros restaurantes. Actividad
concurrente externa puede hacer que este control conservador rechace la carga.

## Datos y escenarios

Con corte `2026-10-31` y semilla `20261031`:

- 2.407 pedidos: 2.315 entregados, 89 no entregados y tres pendientes al corte
  (`Nuevo`, `En preparación`, `Listo`) para consultar priorización.
- 8 productos, 15 insumos, recetas completas, 24 clientes y 4 repartidores.
- 12.416 movimientos: existencias iniciales, compras diarias, consumos por receta
  y ciclo de preparación, y un recuento final trazable.
- Mayor demanda en fines de semana, almuerzo/cena, empanadas y ensaladas en
  crecimiento y milanesas/pastas en descenso. Los pedidos grandes mantienen
  precios normales: el importe elevado proviene de las cantidades.
- Preparaciones lentas, entregas lentas, cliente ausente y nuevas preparaciones
  explícitas por cocción arruinada. Las marcas permiten encontrar los casos.
- Distancias generadas una sola vez entre 0,10 y 5,00 km, con dos decimales.
- Stock final amplio en algunos insumos, bajo en pollo/aceite y una diferencia
  de inventario deliberada de −0,2 kg de lechuga, admitida por HU-09.

La generación difiere confirmaciones cuando todos los repartidores están
ocupados. No hay entregas simultáneas por repartidor; preparación, asignación,
salida y finalización guardan una secuencia temporal válida. El costo de reparto
y los factores de prioridad se obtienen de las funciones actuales del sistema.

Al finalizar, el restaurante queda cerrado y los repartidores no disponibles,
para que el historial exclusivo no reciba pedidos nuevos accidentalmente. Los
tres pendientes son una fotografía del último corte, no pedidos actuales.

Para consultarlo en Oliva, ingresar manualmente con `lucia@hist90.oliva.invalid`
y la contraseña de propietario indicada en el archivo `credentials-*.json` de
esta carga. El panel queda asociado automáticamente al ID dedicado. Los accesos
rápidos anteriores conservan sus cuentas y su restaurante original. En
**Previsión de demanda**, ejecutar el motor cuando se quiera obtener resultados;
en **Indicadores y alertas**, elegir un período histórico con referencia previa
(por ejemplo, 17/10/2026–30/10/2026). **Pedidos**, **Insumos y stock** y
**Repartidores** muestran los registros importados.

## Compatibilidad y límites de los motores actuales

- No se inventan `Cancelado` ni transiciones ausentes: las incidencias usan
  `No entregado` y `nueva_preparacion` ya implementados.
- Seis productos tienen ventas entregadas. Tortilla de papas y berenjenas no
  tienen ventas completadas y aparecen como productos sin ventas históricas.
  El motor aplica los mínimos de siete días/diez pedidos **al restaurante**;
  no existe un umbral independiente por producto. No se cambió esa regla.
- La regresión existente, su MAE, las necesidades de insumos y las alertas del
  10 % se calculan realmente en pruebas de compatibilidad locales. Esas pruebas
  se revierten y **no precargan resultados en Supabase**. No constituyen una
  evaluación de calidad, ajuste del modelo ni la fase 3.
- La diferencia de stock negativo es contable/operativa deliberada; no representa
  existencias físicas negativas. Todas las cantidades se explican por movimientos.
- El generador importa eventos históricos porque la API operativa usa la hora
  real. No agrega endpoints para falsear fechas ni modifica servicios operativos.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_demo_history -q
.\.venv\Scripts\python.exe -m tests.run_postgresql_local tests.test_demo_history_postgresql -q
```

El segundo comando usa exclusivamente PostgreSQL local descartable. Comprueba
carga, 90 días, importes, distancias, secuencia de estados, actores, recetas,
consumos únicos por ciclo, stock, disponibilidad, respaldo, idempotencia,
reinicio, rechazos y rollback; conserva intactos dos restaurantes previos,
incluido uno con el mismo nombre. Ejecuta los motores existentes dentro de una
transacción exterior que finalmente se revierte.
