# DESIGN.md — Identidad visual de la demo de tesis

## 1. Objetivo

Construir una aplicación web para la gestión de pedidos y delivery de restaurantes, con una identidad visual uniforme entre el panel administrativo y las pantallas del cliente (menú, carrito y confirmación del pedido).

La referencia principal es la captura de **Sweetco — Order List** elegida por el autor. Usarla como inspiración visual, no como una plantilla para copiar literalmente. La referencia muestra una interfaz luminosa, sobria, con navegación lateral, tarjetas de pedidos, fotografías de alimentos y acentos verdes suaves.

## 2. Principios visuales

- Interfaz limpia, legible y funcional; evitar elementos decorativos innecesarios.
- Fondo gris muy claro, superficies blancas y acentos verdes suaves.
- Jerarquía clara: título de página, acciones principales y contenido.
- Espaciado consistente y suficiente aire entre componentes.
- No usar degradados llamativos, efectos glassmorphism, colores violetas ni sombras excesivas.
- Priorizar estados visibles y textos claros antes que adornos.
- Diseñar primero para escritorio en el panel administrativo y de manera adaptable a móvil en la experiencia del cliente.

## 3. Tokens de diseño iniciales

Estos valores son una **propuesta aproximada**, no colores extraídos exactamente de la imagen. Centralizarlos en variables CSS o en la configuración de estilos para poder ajustarlos sin modificar cada componente.

| Token | Valor | Uso |
| --- | --- | --- |
| `--color-background` | `#F7F8F7` | Fondo general |
| `--color-surface` | `#FFFFFF` | Tarjetas, paneles, formularios |
| `--color-text` | `#202725` | Texto principal |
| `--color-text-muted` | `#737D78` | Texto secundario |
| `--color-primary` | `#428B72` | Acción principal y elementos activos |
| `--color-primary-soft` | `#E8F5EE` | Estados suaves y fondos seleccionados |
| `--color-border` | `#E5EAE7` | Separadores y bordes |
| `--color-success` | `#2D8660` | Confirmaciones y completados |
| `--color-warning` | `#B37A20` | Advertencias |
| `--color-danger` | `#B94C4C` | Errores y acciones destructivas |

- Tipografía: **Inter**, con alternativas de sistema (`Arial`, `sans-serif`).
- Texto base: 14–16 px. Títulos: 24–30 px, según jerarquía.
- Espaciado: escala de 4, 8, 12, 16, 24 y 32 px.
- Bordes redondeados: 8 px en controles y 12 px en tarjetas.
- Sombras: muy sutiles; preferir bordes finos cuando sean suficientes.
- Botones: altura mínima aproximada de 40 px; foco visible y estados hover, disabled y loading.

## 4. Panel administrativo

- Navegación lateral en escritorio, inspirada en Sweetco: logo o nombre del restaurante, secciones agrupadas y sección activa claramente resaltada.
- Barra superior discreta con título/contexto y controles necesarios.
- Pedidos mostrados en tarjetas o tablas según el volumen de información; fotografías pequeñas cuando aporten valor.
- Cada pedido debe mostrar identificación, productos, cantidades, estado, prioridad y acciones pertinentes sin sobrecargar la tarjeta.
- Indicadores, gráficos y alertas deben compartir los mismos colores, tipografía y espaciados.
- La prioridad y los estados no deben depender únicamente del color: incluir texto o iconos accesibles.

## 5. Interfaz del cliente

- Compartir los tokens visuales y componentes básicos con el panel administrativo, pero **sin reproducir el menú lateral administrativo**.
- Menú gastronómico con fotografías de productos, nombre, descripción breve, precio y acción clara para agregar al carrito.
- Carrito con cantidades editables, subtotal y costo de entrega cuando corresponda.
- Confirmación del pedido con resumen y estado claro.
- Navegación simple y diseño adaptable a pantallas móviles.
- Mantener una experiencia visual cálida gracias a las fotografías de comida, sin romper la estética sobria del sistema.

## 6. Componentes compartidos

Crear componentes reutilizables cuando efectivamente se necesiten: botón, campo de formulario, tarjeta, badge de estado, modal de confirmación, alerta, indicador de carga y estado vacío.

Mantener consistentes: tipografía, bordes, colores, estados interactivos, espaciados y tratamiento de errores. No crear un sistema de componentes excesivamente complejo para la demo.

## 7. Accesibilidad y usabilidad

- Contraste suficiente entre texto y fondo; no usar el verde suave como color de texto sobre blanco si dificulta la lectura.
- Estados de foco visibles y navegación por teclado en controles interactivos.
- Etiquetas explícitas en formularios.
- Diseño responsivo sin desbordamientos horizontales innecesarios.
- Mensajes claros para errores, carga, ausencia de datos y acciones completadas.

## 8. Reglas para Codex

1. Leer este archivo antes de crear o modificar componentes visuales.
2. Respetar la identidad visual tanto en el panel administrativo como en el menú y carrito del cliente.
3. No improvisar una paleta nueva ni cambiar tipografías entre pantallas.
4. Antes de implementar una pantalla nueva, describir brevemente su estructura y los componentes que reutilizará.
5. No agregar librerías de UI ni dependencias visuales sin aprobación.
6. Evitar dashboards genéricos con tarjetas decorativas, métricas ficticias o gráficos sin propósito.
7. Implementar solo los elementos necesarios para el alcance aprobado de la demo.
8. Si existe una captura de referencia dentro del repositorio, consultarla al diseñar y no asumir que los tokens son una reproducción exacta de sus colores.
9. Comprobar el resultado en escritorio y móvil cuando corresponda.
10. No modificar la lógica de negocio para resolver cuestiones puramente visuales.

## 9. Referencia visual

Captura seleccionada por el autor: **Sweetco — Order List**, compartida en la conversación de planificación de la tesis. Guardar una copia en `docs/referencias/sweetco-order-list.png` para que Codex pueda consultarla desde el repositorio.

La referencia es una guía de estilo. No copiar marcas, logotipos, fotografías ni otros activos protegidos sin autorización.
