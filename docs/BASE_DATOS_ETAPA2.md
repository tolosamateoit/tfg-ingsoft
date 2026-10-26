# Etapa 2: esquema propuesto para revisión

Estado: modelos, revisión `0001_der_inicial` y SQL offline preparados.
**No se ejecutó ninguna migración ni escritura en Supabase.** Las reglas de
triggers y actores fueron confirmadas por el autor; aplicar la migración
requiere una aprobación distinta, después de revisar el SQL completo.
Fuente del modelo: `docs/der/der.png`. Los nombres SQL se expresan en minúsculas.

SQL completo para lectura: [sql/0001_der_inicial.sql](sql/0001_der_inicial.sql).
La revisión es una instantánea independiente de los modelos actuales, para
evitar que un cambio futuro en Python altere una migración ya aplicada.

## Tablas y claves

| Tabla | PK | FK | Unicidad adicional |
|---|---|---|---|
| restaurante | id_restaurante | — | — |
| usuario | id_usuario | id_restaurante → restaurante, opcional | correo |
| cliente | id_cliente | id_usuario → usuario | id_usuario |
| producto | id_producto | id_restaurante → restaurante | — |
| insumo | id_insumo | id_restaurante → restaurante | — |
| receta_detalle | (id_producto, id_insumo) | id_producto → producto; id_insumo → insumo | PK compuesta |
| pedido | id_pedido | id_restaurante → restaurante; id_cliente → cliente | — |
| detalle_pedido | id_detalle | id_pedido → pedido; id_producto → producto | — |
| repartidor | id_repartidor | id_usuario → usuario | id_usuario |
| historial_repartidor | id_historial_disp | id_repartidor → repartidor | — |
| entrega | id_entrega | id_pedido → pedido; id_repartidor → repartidor | id_pedido |
| historial_pedido | id_historial | id_pedido → pedido; id_usuario → usuario | — |
| movimiento_stock | id_movimiento | id_insumo → insumo; id_pedido → pedido, opcional | — |
| prediccion_demanda | id_prediccion | id_producto → producto | — |
| alerta | id_alerta | id_restaurante → restaurante | — |

`repartidor` pertenece al restaurante a través de `usuario`; no se agrega una
columna de restaurante a esa tabla ni a las tablas de detalle. Un cliente puede
comprar en distintos restaurantes. Un usuario puede no tener restaurante
(clientes y administración global), conforme a la cardinalidad opcional del DER.
Un pedido tiene como máximo una entrega y cada usuario como máximo un registro
de cliente y uno de repartidor. Roles y autorización se implementarán en las HU.

Los atributos completos están en `backend/app/db/models.py` y se contrastan con
un inventario explícito de columnas en `backend/tests/test_models.py`. Son las
15 entidades del DER, sin campos de bloqueo, ciclos de preparación, fotografías,
descripciones de productos ni `prioridad_calculada_en` añadidos.

## Tipos y nulabilidad propuestos

- Identificadores: `INTEGER` con `IDENTITY`; receta_detalle usa sus dos FK como PK.
- Importes y costos: `NUMERIC(18,2)`, sin punto flotante.
- Cantidades de receta, movimientos y stock: `NUMERIC(18,6)`.
- Cantidades de productos en pedidos: enteros positivos.
- Distancia: `NUMERIC(12,3)` en kilómetros.
- Puntajes, estimaciones, métricas y valores de alertas: `NUMERIC` sin escala fija.
- Marcas temporales: `TIMESTAMP WITH TIME ZONE`; creación por defecto con `now()`.
- Períodos de predicción: `DATE`.
- Factores de prioridad: `JSONB`, nullable hasta que se calculen.
- Horario de atención, roles, estados, unidades y demás textos: `TEXT`.
  No se inventan listas de estados o roles mediante enums en esta etapa.
- `abierto` y `activo`: booleanos obligatorios, sin un valor de negocio implícito.

Pueden ser nulos: usuario.id_restaurante; usuario.telefono; cliente.telefono,
direccion, referencia_local y zona_entrega; pedido.referencia_local,
puntaje_prioridad, factores_prioridad y zona_entrega; repartidor.zona;
historial_pedido.detalle; movimiento_stock.id_pedido y motivo;
prediccion_demanda.nombre_metrica y valor_metrica. El resto es obligatorio.
La imagen no especifica tipos, precisiones ni todos los opcionales descriptivos:
estos son criterios técnicos propuestos para la revisión previa a aplicar SQL.

## Restricciones declarativas ya preparadas en los modelos

- Todas las FK: `ON DELETE RESTRICT` y `ON UPDATE RESTRICT`. Se preservan referencias
  e historiales; no hay borrados en cascada.
- Precios, costos, importe total, distancia y puntaje: no negativos.
- Cantidades de receta y detalle de pedido: mayores que cero.
- Demanda estimada no negativa y fin de período mayor o igual que inicio.
- Índices en FK, aprovechando índices únicos o la PK cuando ya cubren la búsqueda.
- Se permite stock negativo: HU-09 requiere poder detectar esa anomalía.
- No se agrega UNIQUE por pedido/insumo a movimiento_stock: impediría registrar
  una preparación repetida explícita. Su idempotencia por preparación corresponde
  al diseño posterior de HU-04, sin inventar un atributo en esta etapa.

## Integridad entre restaurantes confirmada y preparada

Una FK simple asegura que existe el registro, pero no que ambas referencias
corresponden al mismo restaurante. Sin agregar atributos al DER, la propuesta es
validar en PostgreSQL mediante triggers:

1. receta_detalle: producto e insumo del mismo restaurante.
2. detalle_pedido: pedido y producto del mismo restaurante.
3. entrega: pedido y usuario del repartidor del mismo restaurante; el repartidor
   debe tener restaurante asignado.
4. movimiento_stock: insumo y pedido del mismo restaurante cuando existe pedido.
5. historial_pedido: actor vinculado al mismo restaurante o cliente dueño del
   pedido. La autorización específica por rol pertenece al backend de las HU;
   estos triggers validan pertenencia y titularidad, no reemplazan permisos.
6. Validar también modificaciones en los registros referenciados y bloquear
   cambios que dejen relaciones incompatibles. No basta con revisar INSERT de hijos.
7. La cardinalidad pedido → detalle 1..N exige comprobación diferida al cierre
   de la transacción, para permitir insertar cabecera y detalles juntos.

Estas reglas están implementadas en `backend/migrations/sql/0001_integridad.sql`,
cargado por la revisión inicial. Todavía **no están verificadas mediante
ejecución real en PostgreSQL**: las pruebas de integración se omiten si no hay
una base local descartable configurada.

Para esta demo, los cambios de relaciones adquieren un único advisory lock
transaccional, antes de los locks de filas, y se validan con `READ COMMITTED`.
Esto evita que dos cambios concurrentes válidos por separado dejen un cruce al
confirmarse. Un trigger rechaza niveles de aislamiento con snapshots persistentes
para estos cambios; las lecturas no se restringen. Es una solución conservadora
para un volumen pequeño: serializa cambios de asociaciones, no las consultas ni
actualizaciones normales de precio, stock o estado. No agrega tablas o atributos.

Los triggers diferidos comprueban que cada pedido conserva al menos un detalle,
incluso si se cambia su PK dentro de la misma transacción. Se bloquea TRUNCATE
de detalle_pedido para impedir que eluda esa comprobación; DELETE transaccional
sigue disponible respetando FK y cardinalidad.

Se habilita RLS sin políticas públicas sobre las tablas nuevas y alembic_version,
para que no queden accesibles mediante la Data API de Supabase. FastAPI se conecta
con el usuario PostgreSQL del backend; no se implementan políticas de acceso
por usuario en esta etapa. Las funciones de trigger no son SECURITY DEFINER,
fijan search_path y no se habilitan como RPC públicas.

Las reglas de delivery disponible, transiciones de estados, consumo de stock,
priorización, predicción y autenticación no se implementan en esta etapa.

## Alembic y seguridad de ejecución

`backend/alembic.ini` no contiene una URL ni credenciales. El engine se construye
en memoria con el entorno ya existente y mantiene TLS `verify-full`.
Importar modelos no abre conexiones ni llama a `create_all`.

La modalidad offline usa el dialecto PostgreSQL sin leer el `.env`. La modalidad
online está bloqueada salvo una confirmación explícita `-x approved=true`.
Esa bandera no sustituye la aprobación del autor: no debe usarse antes de revisar
la migración completa. No hay llamadas online en el arranque de FastAPI.

Al aplicar una revisión en el futuro, Alembic necesitará su tabla técnica
`alembic_version`. No es una entidad de negocio ni un cambio del DER.

## Verificación realizada y pendiente

Pruebas actuales: inventario de tablas/columnas, mapeos ORM, compilación del DDL
PostgreSQL, PK compuesta, unicidad, FK, nulabilidad, stock negativo permitido,
engine sin conexión y bloqueo de Alembic online. Se ejecutan con:

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

También se comprueba offline la revisión completa, su reversión y la igualdad
del SQL de revisión con el archivo guardado. Generar SQL, sin acceder a la red
ni leer credenciales, se hace desde `backend/` con:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
```

No se probó inserción, actualización o rechazo de filas en PostgreSQL. Las ocho
pruebas reales preparadas necesitan una base **local, vacía y descartable**, con
nombre que empiece por `tfg_test_`. Creala por separado, y configurá solo en la
terminal de pruebas `TFG_TEST_POSTGRES_DSN` con el formato libpq:

```text
host=127.0.0.1 port=5432 dbname=tfg_test_etapa2 user=USUARIO_LOCAL password=CLAVE_LOCAL
```

Ejecutar después el mismo comando unittest de arriba. El runner rechaza hosts
remotos y bases sin ese prefijo antes de conectar; no lee `backend/.env`.
Aplica la revisión y la revierte exclusivamente en esa base local. No apuntar
esa variable a un túnel ni a una base con información que deba conservarse.

Esas pruebas cubren FK, unicidad, valores, stock negativo permitido, asociaciones
válidas e inválidas, cambios de origen, historial de cliente/personal, cardinalidad
diferida y dos órdenes de escrituras concurrentes. Su omisión no se presenta como
una validación real de PostgreSQL.

Aplicar SQL a Supabase permanece pendiente de aprobación expresa. El downgrade
borra las tablas de la aplicación y sus funciones, sin CASCADE: requiere también
aprobación y respaldo si alguna vez hubiera datos que conservar.
