# Preparación de datos de la demo final

La carga aditiva está en `app.demo_history.preparation`. No crea restaurantes,
no borra registros, no reinicia secuencias ni ejecuta motores analíticos.
No requiere cambios de esquema. Usa PostgreSQL con la revisión 0003 existente.

## Restaurante y ejecución

La inspección de Supabase identificó el restaurante original **Rotisería del
Pueblo, ID 2**, por sus cuentas habituales y pedidos existentes. El ID 3 tiene
el mismo nombre y pertenece al dataset independiente anterior. Se conserva
intacto y la nueva carga lo rechaza como destino.

Desde `backend/`, con la conexión TLS ya configurada:

```powershell
.\.venv\Scripts\python.exe -m app.demo_history.preparation plan --restaurant-id 2
.\.venv\Scripts\python.exe -m app.demo_history.preparation check --restaurant-id 2
.\.venv\Scripts\python.exe -m app.demo_history.preparation load --restaurant-id 2 --execute
.\.venv\Scripts\python.exe -m app.demo_history.preparation validate --restaurant-id 2
```

El corte predeterminado es **31/10/2026 inclusive**, con semilla `20261031`.
Se generan 90 jornadas, **03/08/2026–31/10/2026**, en Buenos Aires. Los instantes
se guardan en UTC: eventos nocturnos del 31 pueden corresponder al 1 de noviembre
en UTC. No se alteran el servidor ni relojes/timestamps de autenticación.
`--cutoff` admite cortes anteriores; se rechazan cortes posteriores al 31/10/2026.

`plan` es offline; `check` y `validate` usan transacciones de solo lectura.
`load` sin `--execute` solo muestra el plan. Repetir con los mismos parámetros
valida y devuelve `unchanged`, sin escrituras en las tablas. Otra semilla,
otro período o tarifas distintas provocan un rechazo; no hay opción de reset.

## Catálogo, inventario e historial

- Diez productos: milanesa, lomito, pizza, hamburguesa, pollo, dos empanadas,
  Coca-Cola, Fanta y cerveza. Se reutiliza la milanesa original y tres insumos
  existentes; se completan recetas y costos de catálogo sin cambiar snapshots
  de precio/costo de pedidos anteriores.
- Diecinueve insumos. Para bebidas, `receta_detalle` representa la equivalencia
  de inventario de una botella/lata por unidad vendida, sin elaboración ficticia.
- Cuatro repartidores adicionales, con dos disponibles y dos no disponibles al
  cierre. Se conserva el repartidor previo. Sus cuentas y 24 clientes de prueba
  tienen el ID del restaurante de destino y correos reservados por restaurante.
- Demanda variable, mayor volumen en fines de semana, preferencias según el día,
  compras de varios productos y asociaciones lomito/Coca-Cola y pizza/Fanta.
- Pedidos grandes por cantidades reales, preparaciones lentas, repetición de
  preparación, entregas demoradas y clientes ausentes. No se falsean reglas de
  integridad para producir anomalías. No se guardan predicciones ni alertas.
- Estados, actores, tarifas reales del restaurante y eventos de entrega se
  persisten. No hay entregas simultáneas entre los cuatro repartidores nuevos.
  El stock conserva saldos anteriores y agrega reposiciones y consumos trazables.

Los saldos previos sin movimientos se concilian mediante un movimiento explícito
de apertura. Es una reconstrucción contable a partir del stock guardado,
**no evidencia de una compra real**. Toda la carga nueva es sintética y se
identifica con `[OLIVA-PREP26:v1]`.

Los clientes pueden comprar en varios restaurantes según el diseño aprobado.
Esta carga verifica que sus clientes nuevos solo tengan pedidos en el destino;
no cambia la autorización ni restringe a los clientes globales existentes.
Los triggers reales siguen impidiendo cruces de productos, recetas, insumos,
repartidores y actores del historial entre restaurantes.

## Conservación y verificación

Antes de escribir se guarda y verifica un respaldo del restaurante en
`.tools/history-demo/`. Las cuentas nuevas usan contraseñas aleatorias y hashes
Argon2id. El archivo privado `preparation-credentials-*.json` contiene los accesos;
las credenciales no se imprimen ni se agregan a Git. Las cuentas habituales de
propietario y personal siguen asociadas al restaurante 2.

La transacción conserva una instantánea previa de todas las tablas de negocio y
autenticación y comprueba la conservación de cada fila existente. Solo admite las
actualizaciones necesarias de catálogo, recetas y stock reutilizados. Pedidos,
detalles, entregas, usuarios, movimientos e historiales previos deben conservarse
exactamente, igual que los registros de los demás restaurantes. Si la validación
o la comparación falla, se revierte toda la carga. Las secuencias PostgreSQL
pueden dejar huecos tras un rollback y nunca se reinician.

La validación compara los pedidos generados contra su plan, importes, costos,
recetas, consumos por ciclo, estados, actores, tiempos, entregas, disponibilidades,
stock conciliado, cobertura temporal y relaciones entre restaurantes.

## Fecha operativa

`app.orders.operational_date.operational_date(db, restaurant_id)` obtiene la
máxima fecha local de pedido persistida del restaurante. Devuelve `None` si
existe el restaurante pero todavía no tiene pedidos; rechaza un ID inválido o
inexistente. La función es interna: el llamador debe usar el restaurante del
contexto autorizado. No se integra aún en pantallas, motores ni autenticación.

## Pruebas reproducibles

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_demo_preparation tests.test_demo_history -q
.\.venv\Scripts\python.exe -m tests.run_postgresql_local tests.test_demo_preparation_postgresql tests.test_postgresql_constraints -q
.\.venv\Scripts\python.exe -m tests.run_postgresql_local tests.test_demo_history_postgresql -q
```

Las integraciones usan exclusivamente Docker/PostgreSQL local descartable.
Comprueban preservación, reutilización, idempotencia, rollback, rechazos de cruces,
semillas incompatibles y fecha operativa con frontera UTC/local, restaurante vacío
y aislamiento. Las pruebas del generador previo verifican su compatibilidad.

Los manifiestos locales reflejan el resultado validado de cada carga. No son un
respaldo global ni sustituyen una consulta posterior sobre PostgreSQL.

## Resultado ejecutado sobre Supabase

Con corte 31/10/2026 y semilla 20261031, el restaurante 2 quedó con 10 productos,
19 insumos, 5 repartidores, 2.421 pedidos y 2.415 registros de entrega. Se
agregaron 2.416 pedidos y 2.413 entregas; los cinco pedidos anteriores y sus
relaciones se conservaron. El historial sintético cubre 03/08/2026–31/10/2026.

La primera ejecución devolvió `action: created`, `validation: passed` y
`existing_records_preserved: true`. La segunda ejecución real devolvió
`action: unchanged`, idénticas cantidades y la misma huella:
`2cbdf9c1a3cabefc16957419269a65bf3248c3926048e9fb0d8bc6fc7b5aad00`.
La fecha operativa consultada en PostgreSQL fue 31/10/2026.

Se ejecutaron las tres órdenes de pruebas anteriores: **5, 12 y 7 pruebas,
respectivamente; todas pasaron**, sin omisiones en esos comandos. El dataset
contiene 2.328 pedidos sintéticos entregados, 85 no entregados y tres pendientes;
cinco preparaciones lentas, cuatro entregas lentas y cuatro pedidos de importe
alto identificados. Estos casos son datos sintéticos, no resultados de modelos.
