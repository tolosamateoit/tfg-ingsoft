# Contexto técnico y funcional de la tesis

**Proyecto:** plataforma web multi-restaurante para gestión de pedidos y delivery con análisis operativo.  
**Fuente de referencia:** «Dev: TESIS_VIGENTE», Google Docs, consultado el 26/10/2026: https://docs.google.com/document/d/18FeunTyDUEuLoCRtkokky5dlJ04Bn5tbNH1kRvNLQZk/edit?tab=t.0  
**Estado:** contexto de desarrollo **provisional**, sujeto a devolución de la profesora. No reemplaza la tesis ni el DER aprobado.

## 1. Propósito y alcance del sistema

La plataforma permite a varios restaurantes registrar pedidos y entregas, administrar menú, recetas, insumos y repartidores, y aprovechar datos operativos e históricos para estimar demanda y necesidades de stock, priorizar pedidos, asignar repartidores y detectar desvíos. Los datos de un restaurante deben mantenerse separados de los demás.

El proceso comienza con la consulta del menú y el registro del pedido y termina con su entrega y trazabilidad. Incluye el almacenamiento y análisis de información operativa e histórica.

## 2. Actores y permisos

- **Cliente:** consulta menú, realiza pedidos, sigue sus propios pedidos y consulta su historial.
- **Personal del restaurante:** gestiona pedidos, menú, preparación, stock y otras funciones operativas según su función.
- **Propietario:** además consulta indicadores, información financiera y asigna personal y repartidores.
- **Repartidor:** consulta entregas asignadas y actualiza sus estados.
- **Administrador de la plataforma:** realiza soporte y diagnóstico de cuentas, sin acceso irrestricto a datos sensibles.

Todos los usuarios se autentican con correo y contraseña. FastAPI debe validar sesión, rol y pertenencia al restaurante **en cada operación protegida**, no solamente en la interfaz. Un cliente no puede acceder a pedidos de otro cliente.

## 3. Historias de usuario oficiales

Las siguientes HU se encuentran en las Tablas 8 a 18 de la tesis. Para el detalle íntegro de sus criterios de aceptación, consultar la fuente; `ALCANCE_DEMO.md` define el recorte implementable, sin reemplazar esos criterios.

| HU | Nombre | Prioridad |
| --- | --- | --- |
| HU-01 | Login | Alta |
| HU-02 | Gestión de menú, productos y recetas | Alta |
| HU-03 | Registro de pedidos | Alta |
| HU-04 | Preparación y movimientos de stock | Alta |
| HU-05 | Repartidores y disponibilidad de delivery | Alta |
| HU-06 | Priorización de pedidos | Alta |
| HU-07 | Asignación y trazabilidad de entregas | Alta |
| HU-08 | Predicción de demanda y necesidades de stock | Alta |
| HU-09 | Indicadores y detección de anomalías | Alta |
| HU-10 | Tablero operativo | Media |
| HU-11 | Administración básica de la plataforma | Media |

## 4. Reglas de negocio que deben implementarse fielmente

### 4.1 Menú, pedidos y delivery (HU-02 y HU-03)

- Cada producto, receta e insumo utilizado en una operación debe corresponder al restaurante autorizado.
- El menú puede consultarse aunque no haya repartidores disponibles.
- Un pedido **con delivery** solo puede confirmarse si el restaurante está abierto y tiene al menos un repartidor disponible.
- La confirmación registra restaurante, productos, cantidades, importe, dirección, medio de pago, fecha y estado inicial.
- Los precios y costos son conceptos distintos. La selección del medio de pago no exige integrar una pasarela de cobro en la demo.

### 4.2 Preparación y stock (HU-04)

- Cada cambio de estado de preparación conserva fecha, hora y usuario responsable.
- Cuando un pedido pasa **por primera vez** a `En preparación`, se descuentan insumos según las recetas de sus productos.
- Se registra **un único movimiento de consumo por pedido e insumo** en esa preparación; cambiar de estado y volver no debe duplicar el descuento.
- Si una preparación se arruina y se realiza una nueva preparación **explícita**, corresponde un nuevo consumo registrado.

### 4.3 Repartidores (HU-05)

- La disponibilidad de delivery requiere restaurante abierto y al menos un repartidor **asignado a ese restaurante** con estado `Disponible`.
- Los cambios de disponibilidad conservan estado, fecha y hora y modifican inmediatamente los candidatos de asignación.

### 4.4 Motor de priorización (HU-06)

La fórmula aprobada es **`P = T + D + G`**:

- `T`: minutos **completos** desde la creación del pedido, sin tope.
- `D = max(0, 10 - distancia_km)`: a 3 km corresponden 7 puntos.
- `G = max(0, (importe_productos - costo_estimado_productos) / 1000)`: importes en pesos argentinos; permite valores decimales.
- Ordenar pedidos activos por `P` **descendente**; en empate, primero el pedido más antiguo y luego el ID menor.
- Mostrar puntaje total y factores `T`, `D` y `G` al responsable.

**No sustituir la fórmula ni agregar ponderaciones inventadas.**

### 4.5 Asignación y trazabilidad (HU-07)

- Procesar los pedidos listos para entregar por prioridad **descendente**.
- Para cada pedido, considerar solo repartidores disponibles **del mismo restaurante**.
- Seleccionar primero al de **menor carga de trabajo asignada**; empate: **mayor tasa de éxito**; nuevo empate: **nombre en orden alfabético**.
- Permitir ajustar manualmente la distancia si la dirección no puede ubicarse en un sistema de geolocalización.
- Guardar secuencia temporal de estados de entrega y permitir seguimiento desde la vista del cliente.

### 4.6 Motor de demanda y necesidades de insumos (HU-08)

- Ejecutar la predicción solo si el restaurante tiene **al menos 7 días de registros y 10 pedidos completados**.
- Si no alcanza esos mínimos, mostrar exactamente **`Historial insuficiente`**, sin producir predicción; el resto del sistema continúa funcionando.
- Con datos suficientes, mostrar demanda estimada y **métrica de evaluación** del modelo.
- Traducir demanda estimada a necesidades de insumos mediante recetas y cantidades, compararlas con stock y alertar faltantes.
- Usar datos sintéticos **identificados como tales** para desarrollo y demostración; las estimaciones deben calcularse realmente, no inventarse en la interfaz.

### 4.7 Indicadores y anomalías (HU-09)

Para el período seleccionado y **solo para el restaurante autorizado**, mostrar:

- Tiempo promedio de preparación: desde inicio hasta listo.
- Tiempo promedio de entrega: desde `En camino` hasta `Entregado`.
- Importe promedio de pedido.
- Stock disponible.
- Disponibilidad de repartidores.

Generar alerta si el tiempo de preparación, tiempo de entrega o importe **supera el promedio de referencia en 10 %**, o si el stock es **negativo**. Cada alerta debe incluir indicador, valor observado, umbral y fecha. Definir de forma reproducible el período y la muestra usados como referencia; no inventar otro porcentaje.

### 4.8 Tablero y soporte (HU-10 y HU-11)

- El tablero integra pedidos activos, alertas de stock, disponibilidad de repartidores e incidencias, siempre filtrados por restaurante.
- La administración global está limitada a diagnóstico y soporte de cuentas, con accesos excepcionales justificados y restringidos.

## 5. Modelo de datos y DER

**La fuente de verdad del esquema es la Figura 4 del Google Docs vigente**, titulada «Diagrama entidad relación del prototipo». El archivo `docs/DER.png` debe ser una **exportación de esa figura aprobada**, no una imagen regenerada ni una versión descartada.

Entidades y conceptos funcionales presentes en la tesis y que deben contrastarse con la Figura 4 antes de definir tablas SQL:

- Restaurante, usuario y cliente.
- Productos, insumos y detalle de receta.
- Pedidos, sus productos/detalles y el historial de estados.
- Repartidores, su disponibilidad/historial y entregas.
- Stock, movimientos de insumos y datos históricos necesarios para analítica.

Relaciones que el modelo debe permitir: restaurante → productos/insumos/pedidos/repartidores; pedido → detalles de productos e historial; producto → receta → insumos; pedido → entrega → repartidor; estados y movimientos con trazabilidad.

**Advertencia importante:** esta sección describe **conceptos y relaciones funcionales**, no certifica nombres exactos de todas las tablas, columnas, PK, FK o cardinalidades de la imagen. Codex debe leer `docs/DER.png` y cotejar cada entidad, atributo y clave **PK/FK** antes de crear migraciones. Si hay campos ilegibles, ausentes o contradictorios, **detenerse y preguntar**, sin inventar el esquema. En particular, no reintroducir `prioridad_calculada_en` si no figura en el DER aprobado.

Comprobaciones críticas de integridad:

- Un pedido de un restaurante no debe contener productos de otro.
- Una receta no debe usar insumos de otro restaurante.
- Una entrega no debe asignarse a un repartidor de otro restaurante.
- La existencia de una FK por sí sola no reemplaza la validación de pertenencia en la lógica del backend.

## 6. Arquitectura y tecnologías aprobadas

- **Aplicación:** web responsive.
- **Frontend:** React + TypeScript.
- **Backend:** Python + FastAPI, con API REST y módulos de predicción de demanda, priorización/asignación y detección de anomalías.
- **Datos:** PostgreSQL.
- **Procesamiento/analítica:** pandas y scikit-learn.
- **Despliegue previsto:** frontend y backend en Render; PostgreSQL en Supabase; backend en Docker; comunicación por HTTPS.
- **Arquitectura:** un backend modular, no microservicios adicionales.

La Figura 11 de la tesis es la referencia visual de arquitectura. `DESIGN.md` rige la identidad visual; `ALCANCE_DEMO.md` define qué parte se implementa ahora.

## 7. Seguridad prevista en la tesis

- Autenticación con email y contraseña; contraseñas protegidas con **Argon2id y sal individual**.
- Contraseñas de 15 a 20 caracteres según el diseño documentado; se admiten frases y espacios y se rechazan claves comunes o comprometidas.
- Bloqueo de ingreso durante **15 minutos tras 5 intentos fallidos consecutivos**, sin revelar existencia del correo.
- Recuperación de contraseña por correo sin enumeración de cuentas, contemplada en el diseño completo (no necesariamente en la demo).
- Mínimo privilegio y denegación por defecto, validación de roles y pertenencia en FastAPI.
- Consultas parametrizadas, validación de entradas y cifrado en tránsito.
- El plan de respaldo y recuperación de la tesis forma parte del diseño general; su alcance efectivo en la demo se decide explícitamente, sin afirmar que está implementado si no lo está.

## 8. Límites para Codex y gestión de cambios

1. Leer `AGENTS.md`, `DESIGN.md`, `ALCANCE_DEMO.md`, este archivo y `docs/DER.png` antes de planificar el modelo de datos.
2. **No generar ni modificar código durante la primera revisión**; proponer un plan para aprobación.
3. No ampliar funcionalidades, agregar dependencias o reinterpretar fórmulas sin autorización.
4. Si la tesis y `ALCANCE_DEMO.md` difieren, **la tesis manda en las reglas de negocio** y el archivo de alcance solo puede simplificar lo implementado para esta entrega.
5. La profesora todavía debe devolver observaciones. Si llega feedback, registrar el cambio y evaluar impacto antes de modificar código, datos o documentos.
6. Antes de implementar SQL, confirmar los nombres exactos de entidades, atributos, PK, FK y cardinalidades de la **Figura 4 aprobada**.
7. Separar datos sintéticos de datos reales; no mostrar cálculos simulados como resultados reales.
8. Implementar y probar por funcionalidad, con cambios acotados y reversibles.

**Este documento sirve para que Codex entienda el dominio y las reglas. No constituye una especificación de base de datos definitiva ni autoriza modificar la tesis.**
