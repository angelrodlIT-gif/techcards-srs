# Propuesta 3 · Cabina de entrenamiento para entrevistas remotas (`TechCards SRS`)

## 1. Concepto y dirección de arte

La **Propuesta 3** transforma TechCards SRS en una **cabina de entrenamiento personal** diseñada para estudiar inglés técnico de IT orientado a entrevistas remotas (AWS/Cloud, Networking, SQL/PostgreSQL y preguntas conductuales STAR). El objetivo es alejarse de los formularios de demo y acercarse al nivel de oficio de herramientas diarias como **Linear, Raycast, Arc y Things**: jerarquía visual clara, velocidad en el teclado, honestidad absoluta con los datos reales y ergonomía nativa en iPhone.

### Paleta y contraste (oscuro por defecto + claro persistente)
- **Tema oscuro por defecto** (recordado en `localStorage` bajo `techcards:propuesta3:theme`, con actualización dinámica de `<meta name="theme-color">`):
  - Lienzo `#0b0c0f`, superficie elevada `#12141a`, superficie secundaria `#181b23`, bordes capilares `rgba(255, 255, 255, 0.085)` y brillo superior sutil (`inset 0 1px 0 rgba(255, 255, 255, 0.05)`).
  - Texto primario `#f2f4f8`, secundario `#a1a8b8`, atenuado `#848c9f` (contraste AA sobre superficies oscuras).
- **Tema claro**: lienzo `#f5f6f8`, tarjetas `#ffffff`, bordes `rgba(15, 23, 42, 0.09)`, texto `#0f1219` / `#475063`.
- **Un solo color de acento fuerte**: **Signal Indigo** (`#5e6cf2` en oscuro, `#4552dc` en claro), usado de forma disciplinada para el CTA principal, el estado activo, el anillo de progreso, las barras de dominio y la escala de intensidad del heatmap de 12 semanas. Los tonos semánticos (verde, ámbar, rojo) se reservan exclusivamente para calificaciones SM-2, estado de conexión y estados de error/aprobación.

### Tipografía y números tabulares
- Familia del sistema (`"Inter", -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif`) y monoespaciada nativa para IDs, atajos y etiquetas técnicas — **cero CDNs ni fuentes externas**.
- **Tracking óptico por tamaño**: títulos y cifra principal con tracking cerrado (`-0.045em` en el contador hero, `-0.03em` en titulares y prompt de estudio), cuerpo en `-0.005em`, etiquetas eyebrow en `+0.05em`.
- **`font-variant-numeric: tabular-nums`** en todos los contadores, anillos, porcentajes, intervalos, fechas, rachas y calificaciones para evitar saltos horizontales al actualizarse.

### Layout y arquitectura sin build
- **Escritorio (≥ 960 px)**: riel lateral izquierdo (`252 px`) con indicador de salud de la API (`/health`), botón directo a la Paleta de Comandos (`Ctrl/Cmd+K`), navegación principal con insignias en vivo (tarjetas pendientes hoy y errores en borrador), interruptor explícito de **Datos demo** (solo lectura, nunca escribe en la API) y cambio de tema.
- **iPhone / móvil (< 960 px)**: barra superior translúcida (`backdrop-filter`) con accesos rápidos y barra inferior de 5 pestañas con zonas seguras (`env(safe-area-inset-*)`) y objetivos táctiles ≥ 44 px.
- **Módulos ES vanilla** en `app/static/propuesta3/`: `index.html`, `styles.css`, `api.js`, `format.js`, `fixtures.js`, `components.js`, `views.js` y `app.js`.
- **IDs seguros como strings**: `api.js` escanea los tokens JSON respetando cadenas escapadas para envolver entre comillas cualquier campo `id` o `*_id` entero antes de `JSON.parse`, y serializa los IDs de vuelta como dígitos crudos sin pasar por `Number` (preservando enteros mayores a `Number.MAX_SAFE_INTEGER`).

---

## 2. Recorrido por las vistas

1. **Cabina (Inicio / Dashboard)**:
   - Saludo según la hora local (`America/Cancun`) + contador gigante tabular de tarjetas que tocan hoy + CTA inmediato a **Modo foco**.
   - **Anillo de progreso SVG** de la sesión de hoy (repasos completados hoy vs. pendientes restantes).
   - **Heatmap de 12 semanas (84 días)** y racha actual calculados con datos reales de `GET /analytics/learning?start=...&end=...` mediante consulta adaptativa (1 sola llamada cuando no hay repasos o todos ocurren en un día; división semanal para rangos activos). Si no hay repasos, muestra una cuadrícula vacía claramente etiquetada y **nunca inventa datos**.
   - **Tiles de mazos** con píldora de pendientes de hoy, barra de dominio real (`repetitions >= 2 && interval_days >= 6`), acceso directo a estudiar y visor modal de tarjetas con carga por bloques de 40 en 40 (para escalar a miles de tarjetas).
2. **Modo foco (Sesión recall-first)**:
   - Pantalla completa (`100dvh`) libre de barras laterales o pestañas inferiores, con barra de progreso superior (`transform: scaleX`).
   - Flujo estricto recall-first: `GET /study/next` (con filtro por tipo y `remediation_only`) → pensar en voz alta → **Revelar** (`POST /study/{id}/reveal` o tecla `Espacio`) → **Calificar 0–5** (`POST /study/{id}/grade` o teclas `0–5`).
   - Soporte para tarjetas `cloze` (resaltando el hueco `____`), `listening` (botón opt-in para `POST /study/{id}/audio` con manejo honesto de `403/409/429/503`) y captura rápida de error desde la tarjeta revelada.
   - **Barra inferior de atajos** en escritorio (`Espacio`, `0–5`, `Ctrl/Cmd+K`, `Esc`) y **pantalla de resumen** al concluir la cola con tasa de recuerdo, calificación media y distribución 0–5.
3. **Crear y curar material**:
   - **Generar desde texto** (`POST /cards/generate`, validación inline ≥ 10 caracteres, vista inmediata de las tarjetas generadas).
   - **Tarjeta manual** (`POST /cards`) para los 7 formatos con validación inline para `cloze` (`____` único) y `listening` (≤ 1,000 caracteres).
   - **Galería de plantillas** (`GET /templates`, `POST /templates/{id}/cards`) filtrable por `STAR` y `Networking`, con guía expandible y follow-ups.
   - **Fuentes** (`GET/POST/DELETE /sources`, `POST /sources/{id}/approve`, `POST /sources/{id}/discard`) con manejo explícito de conflictos `409` (URL duplicada o estado no borrador).
4. **Tablero de errores (3 columnas)**:
   - Columnas **Pendiente (`draft`) / Aprobado (`approved`) / Descartado (`discarded`)** en escritorio, y pestañas por columna en iPhone.
   - Modal dual para sugerencia heurística (`POST /errors/suggest` con casilla obligatoria de consentimiento explícito `consent: true`) o registro manual (`POST /errors`), aprobación con previsualización de tarjeta (`POST /errors/{id}/approve`), descarte (`POST /errors/{id}/discard`), borrado opcional en cascada (`?delete_card=true`) y exportación JSON (`GET /errors/export`).
5. **Analítica (`GET /analytics/learning`)**:
   - Filtros rápidos (`Todo`, `7 días`, `30 días`, `12 semanas`) y rango personalizado con validación inline `start <= end` (`422`).
   - KPIs reales de recuerdo, recaída, sesiones, duración observada y recuerdo del primer repaso en tarjetas de remediación, más panel transparente de calidad de datos y nota explícita para métricas aún no registradas (`active_study_seconds`, `response_seconds`).
6. **Paleta de comandos (`Ctrl/Cmd+K`)**:
   - Apertura y cierre instantáneos (0 ms), búsqueda por vistas, mazos con pendientes y acciones rápidas, navegable al 100 % con teclado (`↑`, `↓`, `Enter`, `Esc`).

---

## 3. Aplicación y hallazgos de cada skill

### 1) `emil-design-eng` + `apple-design`
- **Qué revisó**: jerarquía de encabezados, estados de presión (`:active`), curvas de aceleración personalizadas, materiales translúcidos, contraste del badge `<kbd>` sobre botones primarios y duplicación de texto en el panel lateral del heatmap.
- **Qué cambió**:
  - Se fijaron curvas personalizadas (`--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`, `--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1)`) y respuesta táctil inmediata `:active { transform: scale(0.97) }` en botones y controles.
  - Se añadió `[hidden] { display: none !important; }` tras detectar en la inspección visual que `display: flex` en `.demo-banner` y `display: grid` en `.demo-variant-bar` anulaban el atributo `hidden`.
  - Se rediseñó el heatmap de celdas rectangulares estiradas (72×22 px) a una matriz compacta de cuadros precisos (`16×16 px`) con etiquetas de día de la semana y panel de lectura lateral sin texto duplicado.
  - Se ajustó `.btn-primary .kbd` a blanco translúcido para integrarse visualmente dentro del botón azul-índigo, y se dio `flex: 1` al bloque de título en `.view-header` para mantener las acciones alineadas a la derecha en escritorio.
  - Se añadieron soportes para `prefers-reduced-transparency: reduce` (chrome sólido sin `backdrop-filter`) y `prefers-contrast: more`.

### 2) `break-ui`
- **Qué probó**: se construyó el conjunto `Peor caso` en `fixtures.js` (accesible mediante el interruptor **Datos demo → Peor caso** o `?data=worst`, sin escribir nunca en la API) con IDs > `Number.MAX_SAFE_INTEGER` (`9007199254740993123`, `18446744073709551601`), nombres largos con guiones, diacríticos vietnamitas (`Đặng Thị Ngọc Hân`), CJK (`王秀英`), RTL (`نور الهدى`), emoji ZWJ (`👩🏽‍💻`), nombre de 1 carácter (`J`), URLs sin espacios, payloads `<script>alert(1)</script>`, conteos `0`, `1` y `10,000` tarjetas, y zoom al 200 % a 320 px de ancho.
- **Qué rompió y cómo se arregló**:

| # | Severidad | Elemento | Valor de peor caso | Qué ocurrió a 320 px | Solución aplicada |
| --- | --- | --- | --- | --- | --- |
| 1 | **Roto** | `#template-deck-target` (`<select>`) | Nombre de mazo de 108 caracteres | Desbordó horizontalmente el viewport en **+623 px** (`scrollWidth: 928`) | `width: min(260px, 100%); max-width: 100%; text-overflow: ellipsis` y `min-width: 0` en el contenedor padre (`views.js`, `styles.css`). |
| 2 | **Visual** | `.demo-banner-actions` | Banner demo a 320 px | Desbordó **+5 px** al no envolver los controles | `flex-wrap: wrap; max-width: 100%` en `.demo-banner-actions` (`styles.css`). |
| 3 | **Visual** | `.heatmap-grid` | 12 columnas de 16 px a 320 px | Sobresalía 7 px en iPhone SE (320 px) | `min-width: 0` en `.heatmap-scroll` + reducción responsive a cuadros de `13×13 px` (`gap: 4px`) bajo `max-width: 375px` (`styles.css`). |
| 4 | **Frágil** | `.btn` y `.tabbar-label` | Zoom 200 % (`32px`) a 320 px | Botones con `white-space: nowrap` empujaban el ancho del documento | `white-space: normal; max-width: 100%` en botones bajo `560px` y `text-overflow: ellipsis` en `.tabbar-label` (`styles.css`). |

- **Verificación posterior**: re-ejecutada la auditoría en las 8 vistas/estados con `?data=worst` a 320 px → **`docOverflow: 0`**, **0 XSS**, **0 `NaN`/`undefined`**.

### 3) `mobile-native`
- **Qué aplicó**:
  - Viewport con `viewport-fit=cover` e `interactive-widget=resizes-content` (nunca `user-scalable=no`).
  - Doble soporte de `theme-color` actualizado dinámicamente al alternar oscuro/claro.
  - `-webkit-tap-highlight-color: transparent`, `-webkit-text-size-adjust: 100%`, `overscroll-behavior: none` en raíz y `overscroll-behavior: contain` en paneles desplazables.
  - Altura dinámica `100dvh` y relleno con `env(safe-area-inset-*, 0px)` en barra superior, tabbar inferior, toasts y hojas modales.
  - `font-size: 16px` en todos los `input`, `textarea` y `select` para evitar el zoom automático de iOS Safari.
  - `touch-action: manipulation` y `user-select: none` únicamente en controles (nunca en `body`, manteniendo copiable el contenido de las tarjetas y errores).
  - Todos los `:hover` encapsulados en `@media (hover: hover) and (pointer: fine)` para evitar estados pegados en pantallas táctiles.
  - Botón redundante `Comandos Ctrl K` oculto en el hero móvil (< 960 px) ya que la barra superior móvil incluye el botón táctil de búsqueda (44×44 px), y barra inferior de atajos oculta en `@media (pointer: coarse)`.
- **Verificación pendiente en hardware físico**: la emulación de navegador valida el layout a 390 px / 320 px y las reglas CSS, pero el comportamiento real del teclado virtual de iOS Safari, las zonas seguras del Dynamic Island y el rebote de scroll requieren confirmación en un iPhone físico.

### 4) `find-animation-opportunities` + `animate` + `choreograph`
- **Candidatos rechazados deliberadamente**:
  - **Paleta de comandos (`Ctrl/Cmd+K`)**: rechazada — acción de teclado de alta frecuencia (100+/día); abre y cierra en **0 ms**.
  - **Revelar respuesta y cambiar tarjeta en Modo foco**: rechazada — bucle central repetido cientos de veces; transición instantánea sin giro 3D ni retardo artificial.
  - **Cambio de vistas / pestañas**: rechazada — navegación principal instantánea.
  - **Celdas del heatmap y KPIs de analítica**: rechazadas — datos funcionales que el usuario lee y compara.
- **Animaciones aprobadas y construidas**:
  - Feedback táctil `:active` (`transform: scale(0.97)`, `140ms var(--ease-out)`).
  - Toasts interrumpibles con `@starting-style` y transiciones CSS (`transform, opacity`, entrada `400ms ease`, salida `200ms var(--ease-out)` por el mismo borde inferior; temporizador pausado en hover o cuando la pestaña queda oculta).
  - Modales y hojas móviles con `@starting-style`: en escritorio escalan centrados desde `scale(0.96)` + `opacity: 0` (`220ms var(--ease-out)` entrada / `150ms` salida); en móvil deslizan desde abajo (`translateY(100%)`, `320ms var(--ease-drawer)`).
  - Pantalla de resumen al completar sesión (presupuesto de deleite, frecuencia rara): coreografía no uniforme con tiempos decrecientes (Lead `0ms`, Stats `55ms`, Acciones `85ms`, Distribución solo fade `95ms`, total < 290 ms, nunca bloquea clics).

### 5) `review-animations`
Auditoría final sobre `styles.css`:

| Antes | Después | Por qué |
| --- | --- | --- |
| `.deck-tile { transition: border-color 140ms ease, transform 140ms var(--ease-out); }` | `.deck-tile { transition: border-color 140ms ease; }` | `.deck-tile` no aplica `transform`; declarar transiciones sin uso desperdicia capas de composición. |
| `.toast { transition: transform 350ms ease, opacity 350ms ease; }` | `.toast { transition: transform 400ms ease, opacity 400ms ease; }` | Alineado al estándar Sonner (`400ms ease` en entrada, salida rápida `200ms var(--ease-out)`). |
| `.switch-track::after` mantenía `transform` bajo `prefers-reduced-motion: reduce` | Añadido `.switch-track::after { transition: none; }` en la media query | Elimina movimiento traslacional innecesario cuando el usuario solicita movimiento reducido. |

- **Veredicto `review-animations`**: **Aprobado** — cero `transition: all`, cero `scale(0)`, cero `ease-in`, cero animaciones en atajos de teclado, propiedades GPU (`transform`/`opacity`) únicamente, todos los `:hover` restringidos por capacidad del puntero y `prefers-reduced-motion` respetado en toda la app.

### 6) `pick-ui-library`
- No se instaló ninguna librería externa (cero dependencias y cero build según el contrato del proyecto). Los primitivos críticos (modal con trampa de foco y restauración, paleta de comandos con `role="listbox"`, toasts interrumpibles) se implementaron con semántica ARIA explícita y código modular auditable.

---

## 4. Deuda pendiente y mejoras futuras

- **Pruebas en iPhone real**: validar en Safari iOS físico el comportamiento de `100dvh` con teclado abierto en el formulario de crear tarjetas y el modal de sugerir errores, además del ajuste exacto de `env(safe-area-inset-*)` en modo PWA.
- **Paginación incremental en `/cards` por encima de 1,000 tarjetas**: actualmente `fetchAllPages` trae hasta 10 páginas (1,000 tarjetas) por mazo y renderiza en bloques de 40 en el inspector; si un mazo supera las 1,000 tarjetas reales en API, convendría añadir un botón "Cargar más desde servidor" conectado a `offset`.
- **Edición inline de tarjetas y errores en borrador**: el backend expone `PUT /cards/{id}`, `PUT /errors/{id}` y `PUT /sources/{id}`; hoy la UI prioriza creación, aprobación, descarte y borrado, dejando la edición detallada de tarjetas/errores individuales como siguiente iteración.
- **Métricas de tiempo activo**: `active_study_seconds` y `response_seconds` se muestran honestamente como "No medido aún" hasta que el backend incorpore esa telemetría.
