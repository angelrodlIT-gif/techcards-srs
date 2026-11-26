# Propuesta 1 — Diseño e Implementación («Atelier de Estudio»)

Documento de diseño y auditoría técnica para `/propuesta1/` de **TechCards SRS**. Redactado antes de programar la interfaz y completado tras ejecutar cada skill obligatoria sobre la implementación real.

---

## 1. Exploración de conceptos (previa a la implementación)

Los pilotos previos (`#45`, `#48`, `#49`) cumplieron el flujo mínimo pero se percibían como formularios de demostración: cajas apiladas sin jerarquía, poca respiración tipográfica y ausencia de identidad diaria. Se evaluaron tres direcciones distintas:

### Concepto A — «Atelier de Estudio» (Editorial táctil + precisión de instrumento)
- **Referentes:** Things 3, Readwise Reader, iA Writer, objetos industriales de Braun / Dieter Rams.
- **Carácter:** Papel mineral cálido en modo claro (`#F6F4EF`) y tinta carbón cálida en modo oscuro (`#141311`), fichas físicas con elevación sutil y folio técnico, serif editorial para las preguntas y respuestas de estudio, sans limpia para la navegación y cifras tabulares alineadas para métricas e intervalos SM-2.
- **Acento:** Bermellón editorial (`#C24124` en claro / `#C84323` en botones en oscuro con contraste WCAG AA > 5:1) reservado para la acción principal de estudio y el foco activo; verde salvia (`#1D6846` / `#4EC48B`), ámbar ocre (`#9B560A` / `#EBB052`) y azul pizarra (`#225582` / `#78B4E8`) para estados semánticos.

### Concepto B — «Obsidian Studio» (Oscuro ultradenso estilo Linear / Raycast)
- **Carácter:** Fondo `#0B0C0E`, bordes traslúcidos `1px`, acento índigo/violeta, densidad alta tipo herramienta de incidencias.
- **Descarte:** Es la estética más predecible para software técnico (el propio índice `/propuestas` ya usa negro + violeta `#7c5cff`). Para sesiones diarias de lectura y habla en voz alta de 20–40 minutos, un contraste oscuro y denso genera fatiga visual y recuerda a un visor de logs más que a un espacio de estudio.

### Concepto C — «Sprint Diario» (Gamificación vibrante estilo Duolingo)
- **Carácter:** Colores muy saturados, insignias grandes, rachas y medidores destacados.
- **Descarte:** La API real de TechCards SRS no expone rachas, XP ni vidas. Forzar un lenguaje gamificado sin esos datos produciría secciones huecas o presión para inventar métricas, rompiendo la regla de honestidad de datos.

### Decisión elegida: **Concepto A — «Atelier de Estudio»**
Se elige el Concepto A porque:
1. **Resuelve el uso diario real:** estudiar vocabulario técnico, frases de entrevista y respuestas STAR exige calma lectora, foco en una sola ficha y cero ruido visual.
2. **Se siente producto real sin inventar datos:** la jerarquía tipográfica, el sistema de fichas y las ilustraciones vectoriales limpias hacen que incluso los estados vacíos o con pocas sesiones se perciban intencionales y serenos.
3. **Diferenciación inmediata:** frente a formularios planos o paneles dark-violet genéricos, el contraste papel cálido + tinta + bermellón + serif/sans/mono crea personalidad memorable con cero dependencias externas.

---

## 2. Dirección de arte

### Paleta de colores (contraste WCAG AA verificado)
| Token | Modo claro (Papel) | Modo oscuro (Tinta) | Uso |
| --- | --- | --- | --- |
| `--bg` | `#F6F4EF` | `#141311` | Lienzo base |
| `--bg-elevated` | `#ECE8DF` | `#1D1B18` | Barra lateral escritorio |
| `--surface` | `#FFFFFF` | `#1E1C19` | Fichas, tarjetas, paneles |
| `--surface-subtle` | `#F1EEE6` | `#272420` | Cabeceras de ficha, pestañas, bloques |
| `--ink` | `#1C1917` | `#F3F0E9` | Texto principal |
| `--ink-muted` | `#665F59` | `#A49D92` | Metadatos y subtítulos |
| `--accent` / `--accent-btn` | `#C24124` | `#EB6B4B` / `#C84323` | Foco activo y botones primarios (AA con blanco) |
| `--success` | `#1D6846` | `#4EC48B` | Retención aprobada, estado `approved` |
| `--warning` | `#9B560A` | `#EBB052` | Borradores (`draft`), calificaciones medias |
| `--danger` | `#B4232A` | `#F27277` | Errores de API, recaídas, descarte/borrado |
| `--info` | `#225582` | `#78B4E8` | Plantillas, fuentes, etiquetas de formato |

### Tipografía (cero CDNs, pilas nativas)
- **Editorial (`--font-serif`):** `"Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif` — titulares de página y el cuerpo de pregunta/respuesta de cada ficha de estudio.
- **Interfaz (`--font-sans`):** `ui-sans-serif, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif` — navegación, formularios, botones y cifras KPI (`lining-nums tabular-nums`).
- **Instrumento (`--font-mono`):** `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace` — intervalos SM-2 (`1 d`, `6 d`), factor de facilidad (`2.50`), teclas rápidas (`Espacio`, `0`–`5`), fechas y contadores.
- **Calibración óptica (Apple Design):** tracking negativo en titulares grandes (`-0.025em`) y cifras KPI (`-0.03em`), neutro en cuerpo, positivo en microetiquetas (`+0.06em`) y cuadrículas expresadas en `rem` para acompañar la escala de texto del sistema.

### Arquitectura de layout
- **Escritorio (≥ 900 px):** barra lateral fija de `256 px` con 5 destinos nombrados por contenido (**Inicio**, **Estudiar**, **Crear**, **Errores**, **Analítica**), interruptor limpio `API real | Datos demo` y selector de tema (`Auto` / `Claro` / `Oscuro`). Lienzo principal limitado a `1080 px` (`760 px` en sesión de estudio).
- **Móvil / iPhone (320–899 px):** cabecera pegajosa translúcida con `env(safe-area-inset-top)`, barra inferior translúcida (`backdrop-filter: blur(22px)`) con `env(safe-area-inset-bottom)` y 5 destinos con objetivos táctiles ≥ 44 × 44 px. Altura gestionada con `100dvh`.

---

## 3. Recorrido por las vistas y fidelidad a la API

1. **Inicio (`#inicio`):** consulta `GET /decks`, `GET /decks/{id}/due`, `GET /cards?deck_id=...` y `GET /errors?status=draft` (con paginación automática). Muestra 4 métricas reales, el mazo prioritario del día, cuadrícula de mazos con barra de avance real, modal `<dialog>` nativo para crear/editar/eliminar mazos y visor paginado de fichas por mazo (25 por página).
2. **Estudiar (`#estudiar`):** flujo estrictamente *recall-first* con `GET /study/next` (la respuesta nunca se descarga antes de revelar), selector de mazo, filtro de formato (`vocabulary`, `interview_phrase`, `behavioral`, `sentence`, `cloze`, `es_en`, `listening`), interruptor `remediation_only`, soporte opt-in de audio Polly (`POST /study/{id}/audio` con `polly-opt-in: true`), revelación (`POST /study/{id}/reveal` / tecla `Espacio`), botonera SM-2 `0–5` (`POST /study/{id}/grade` / teclas `0–5`) con vista previa determinista del próximo intervalo y resumen final honesto basado en los `ReviewOut` reales de la sesión.
3. **Crear (`#crear`):** 4 sub-pestañas: **Generar desde texto** (`POST /cards/generate` con contador de caracteres 10–20 000 y `max_cards` 1–20), **Plantillas** (`GET /templates`, filtro `STAR` / `Networking`, vista completa con follow-ups y alta con `POST /templates/{id}/cards`), **Fuentes** (`/sources`, manejo de conflicto `409` por URL duplicada, edición `PUT`, descarte y aprobación a tarjeta), y **Mazo / Manual** (`POST /decks` y `POST /cards` con validación en vivo de `cloze` con hueco único `____` y límite de 1000 caracteres en `listening`).
4. **Errores (`#errores`):** panel **Sugerir corrección** (`POST /errors/suggest` con casilla de consentimiento explícito obligatorio `consent: true` y previsualización inline de `suggested_card`), registro manual (`POST /errors`), filtros por estado (`draft`, `approved`, `discarded`), comparación lado a lado (*Lo que dijiste* vs *Forma corregida*), aprobación editable (`POST /errors/{id}/approve`), descarte (`POST /errors/{id}/discard`), borrado y exportación JSON (`GET /errors/export`).
5. **Analítica (`#analitica`):** consulta `GET /analytics/learning` con filtros `start`/`end` (validación `start <= end`), tarjetas KPI honestas que muestran `"Sin datos"` cuando el denominador es `0`, nota transparente para `active_study_seconds` y `response_seconds` (`null` en la API actual), embudo real de corrección de errores y panel de integridad (`data_quality`) con zona horaria `America/Cancun`.

### Seguridad de IDs enteros grandes (`> Number.MAX_SAFE_INTEGER`)
- `parseApiJson()` en `api.js` empareja cadenas JSON completas primero (para no alterar texto libre dentro de las tarjetas) y convierte a cadena decimal los valores enteros de cualquier clave `id` o `*_id` antes de `JSON.parse`.
- `serializeApiJson()` emite de vuelta los campos `id` y `*_id` validados (`/^[1-9]\d*$/`) como dígitos crudos sin comillas en el JSON saliente, evitando cualquier conversión a `Number` IEEE-754. Nunca se hace aritmética con IDs.

---

## 4. Qué encontró y qué cambió cada skill

### 1. `emil-design-eng` + `apple-design`
| Antes | Después | Por qué |
| --- | --- | --- |
| `--accent: #EB6B4B` con texto blanco en botones primarios de modo oscuro (~3.4:1) | `--accent-btn: #C84323` con `#FFFFFF` (> 5.1:1 WCAG AA) manteniendo `#EB6B4B` para acentos de texto | Contraste AA real en botones sin perder la identidad bermellón |
| Cifras KPI en serif Georgia con números de estilo antiguo (`4`, `5`, `7` descendían bajo la línea base) | `--font-sans` con `font-variant-numeric: lining-nums tabular-nums` y tracking `-0.03em` | Alineación precisa de cifras y cero saltos horizontales al actualizar contadores |
| `"Sin datos"` en Analítica con el mismo tamaño y peso que `"100 %"` | `.kpi-number--empty` más discreto (`1.35rem`, `--ink-muted`) y `min-height: 2.3rem` en etiquetas KPI | Los valores vacíos no compiten visualmente con métricas reales y los números comparten línea base |
| `.deck-grid` con `minmax(300px, 1fr)` dejaba 1/3 vacío en escritorio con 2 mazos | `repeat(auto-fit, minmax(min(100%, 20.5rem), 1fr))` | Equilibrio natural con 2 mazos y adaptación fluida a 3+ en pantallas amplias |
| `.grade-btn` con `border-top: 3px solid` generaba un bisel irregular en las esquinas redondeadas | `box-shadow: inset 0 3px 0 0` + `overflow: hidden` | Franja superior nítida y uniforme en cada botón 0–5 |
| Enlace subrayado de depuración (`break-ui`) visible en la barra lateral por defecto | Barra lateral limpia solo con `API real \| Datos demo`; los modos de estrés viven dentro del banner de vista previa o `?data=worst` | Elimina ruido de desarrollo del chrome principal |
| Doble petición inicial a `/decks` al entrar directo en `#inicio` | Omitir `refreshGlobalBadges()` en arranque cuando la ruta activa es `inicio` | Evita tráfico redundante manteniendo contadores exactos |

### 2. `break-ui` (prueba con `?data=worst` y `?data=empty`)
Se montó un conjunto de estrés de solo lectura con nombres de 120 caracteres, emoji ZWJ (`👩🏽‍💻`), diacríticos vietnamitas (`Đặng Thị Ngọc Hân`), texto RTL árabe (`نور الهدى عبد الرحمن`), cadenas HTML/XSS literales (`<script>alert(1)</script>`), URLs irrompibles, IDs de 19 dígitos (`9007199254740993123`), 0 tarjetas, 1 tarjeta y 10 000 tarjetas.

- **Roto detectado en 320 px:** `.segmented` de 4 estados (`Todas | Borradores | Aprobadas | Descartadas`) desbordaba horizontalmente `#crear?tab=fuentes` (`368 px`) y `#errores` (`370 px`).
  - **Cambio:** `max-width: 100%; overflow-x: auto; overscroll-behavior-x: contain; touch-action: pan-x;` en `.segmented`. Resultado en 320 px: `0 px` de desbordamiento horizontal en las 8 rutas.
- **Roto detectado al 200 % de escala de texto (320 px):** `.btn` con `white-space: nowrap`, `.page-actions` con `flex-shrink: 0` sin `max-width: 100%` y `.mobile-header` sin `flex-wrap` empujaban el ancho hasta `606–730 px`.
  - **Cambio:** `.btn` con `white-space: normal; max-width: 100%`, `.mobile-header` con `flex-wrap: wrap`, `.page-actions` y `.focus-hero-actions` con `min-width: 0; max-width: 100%`, `.badge` con `max-width: 100%; text-overflow: ellipsis`, y cuadrículas (`.stats-strip`, `.grade-grid`, `.kpi-grid`) con `minmax(min(100%, ...rem), 1fr)`.
- **Lo que resistió desde el principio:** pluralización española con `Intl.PluralRules` (`1 tarjeta`, `1 pendiente`, `10,000 tarjetas`), división segura por cero en barras de progreso y KPIs, escape estricto sin `innerHTML` y preservación exacta de IDs de 19 dígitos.

### 3. `mobile-native` (auditoría en 390 px y 320 px)
- **Hallazgo real en auditoría de cajas táctiles:** `.btn--sm` (`38 px`), `.chip-toggle` (`36 px`), `.seg-btn` (`34 px`) y `.toast-close` (`32 px`) quedaban por debajo del mínimo táctil de `44 px` en móvil.
  - **Cambio:** todos suben a `min-height: 44px` por defecto (móvil y puntero grueso), conservando altura compacta solo bajo `@media (min-width: 900px) and (pointer: fine)`. Re-verificado con `getBoundingClientRect()`: `0` controles por debajo de `44 px` en todas las vistas a 320 px y 390 px.
- **Plataforma aplicada:** `viewport-fit=cover, interactive-widget=resizes-content` (sin `user-scalable=no` ni `maximum-scale=1`), doble `<meta name="theme-color">` sincronizado al cambiar de tema, `100dvh`, `env(safe-area-inset-*)`, entradas a `16px` mínimo, `-webkit-tap-highlight-color: transparent`, `touch-action: manipulation`, `overscroll-behavior: none` en raíz y `contain` en modales/sidebar, `user-select: none` solo en controles (nunca en `body`) y todos los `:hover` encerrados en `@media (hover: hover) and (pointer: fine)`.
- **Pendiente de hardware real:** el tacto físico de iOS Safari (barra de URL colapsando, teclado virtual y safe areas del notch/Dynamic Island) no puede verificarse desde emulación de navegador y debe confirmarse en iPhone físico.

### 4. `find-animation-opportunities` + `animate` + `choreograph`
**Compuerta de movimiento aplicada (qué SÍ anima):**
1. **Pulsación de botones y controles (`:active`):** `transform: scale(0.97)` en `140ms var(--ease-out)` — propósito: *feedback* inmediato (frecuencia: decenas/día, sutil y sub-160 ms).
2. **Notificaciones toast:** `@starting-style` + `transform: translateY(100%)` + `opacity`, `400ms ease` al entrar y `240ms` al salir por el mismo borde — propósito: *consistencia espacial* (frecuencia: ocasional; pausa temporizador si la pestaña queda oculta).
3. **Modal `<dialog>` nativo:** `scale(0.96)` + `opacity: 0`, centrado (`transform-origin: center`), `220ms var(--ease-out)` al entrar y `170ms` al salir — propósito: *evitar aparición brusca* (frecuencia: ocasional).
4. **Botón destructivo «mantener para eliminar»:** `clip-path: inset(0 100% 0 0)` → `inset(0 0 0 0)` con temporización asimétrica (`1.2s linear` al mantener, `180ms var(--ease-out)` al soltar) — propósito: *feedback deliberado anti-errores* (incluye doble pulsación accesible para teclado).
5. **Resumen de fin de sesión:** coreografía de 3 bloques con retrasos no uniformes decrecientes (`0ms` / `240ms`, `50ms` / `220ms`, `90ms` / `200ms` → total `290ms` < 300 ms), colapsada a un fade único en `prefers-reduced-motion` — propósito: *deleite* reservado a momento raro de finalización.

**Candidatos rechazados deliberadamente:**
- **Revelar respuesta y calificar `0–5` en Estudiar:** *Rechazado — acción 100+/día disparada por teclado (`Espacio`, `0–5`). Cambio instantáneo sin animación.*
- **Cambio de pestañas y navegación entre vistas:** *Rechazado — navegación frecuente; sin retrasos ni entradas en cascada.*
- **Barras de analítica y embudo de errores:** *Rechazado — datos funcionales de lectura; la decoración estorba.*
- **Hover sobre tarjetas en pantallas táctiles:** *Rechazado — encerrado en `@media (hover: hover) and (pointer: fine)`.*

### 5. `review-animations`
- Verificado contra los 10 estándares: sin `transition: all`, sin `scale(0)`, sin `ease-in`, todas las curvas desde tokens (`--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`), solo propiedades GPU (`transform`, `opacity`, `clip-path`), salida de modal más rápida que entrada (`170ms` vs `220ms`), coreografía de resumen acotada a `290ms`, y `prefers-reduced-motion: reduce` reduce movimiento a transiciones suaves de opacidad/color en lugar de cortar toda retroalimentación.
- **Veredicto interno:** Aprobado sin regresiones de sensación.

### 6. `pick-ui-library`
- **Decisión:** cero librerías externas en runtime para respetar la restricción local sin build ni CDNs. Se usó el elemento nativo `<dialog>` para foco y cierre con `Escape`, `Intl.*` nativo para formato/pluralización y CSS transitions/WAAPI-compatible sin bundle adicional.

---

## 5. Deuda pendiente

- **Verificación en iPhone físico:** confirmar safe areas reales, comportamiento del teclado virtual en formularios largos (`Crear` / `Errores`) y ausencia de destellos táctiles en Safari iOS real.
- **200 % de zoom de texto en 320 px en casos extremos combinados:** al forzar `font-size: 200%` sobre `320 px` con datos de estrés (`?data=worst`), 4 vistas (`#estudiar`, `#crear?tab=generar`, `#crear?tab=fuentes`, `#crear?tab=manual`) quedan en `0 px` de desbordamiento, mientras que los controles segmentados de 4 etiquetas largas en `#errores` / `#inicio` pueden requerir desplazamiento horizontal interno o apilado en 2×2 si se desea cero scroll horizontal incluso en `320 px` a 200 %.
- **Edición inline de tarjetas individuales:** actualmente el visor de fichas de un mazo permite inspeccionar y eliminar (`DELETE /cards/{id}`); añadir un modal de edición (`PUT /cards/{id}`) queda como mejora natural futura.
- **Soporte de síntesis de audio Polly:** la UI implementa `POST /study/{card_id}/audio` con `polly-opt-in: true` y maneja `403`/`409`/`429`/`503`, pero no se probó reproducción de audio real porque requiere credenciales AWS Polly locales.
