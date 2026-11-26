# Observatorio de memoria

## Tres conceptos

**Observatorio.** Una estación nocturna con cartas celestes, una luna grabada y mandos ámbar. La cola del día ocupa el primer plano y el resto del historial queda en instrumentos secundarios.

**Herbario.** Un archivo botánico donde cada mazo tiene una cubierta de papel prensado. Funcionaría bien como colección, aunque el siguiente repaso tendría menos protagonismo.

**Mesa de montaje.** Una sala de edición con pistas horizontales para las sesiones. Su gramática depende demasiado del ancho de pantalla.

Elegí el Observatorio. La oscuridad enmarca la pregunta al estudiar y la carta lunar da identidad al inicio incluso cuando la biblioteca está vacía. Las órbitas son ilustraciones decorativas. Todos los contadores se obtienen de la API.

## Plan

El contrato de datos precede al diseño del inicio. La sesión conserva una cola de identificadores y preguntas, la respuesta revelada y las notas confirmadas. Un módulo de transporte conserva los identificadores decimales. El taller puede implementarse independientemente del inicio y la sesión; cada envío se bloquea mientras espera confirmación. La verificación recorre los flujos con SQLite, datos límite y dos tamaños de pantalla.

## Dirección de arte y recorrido

El fondo de tinta (#101519) y los paneles de grafito (#181f24) enmarcan el grabado lunar original. El ámbar (#f2ba87) identifica el próximo repaso y la navegación activa. Los títulos usan las serif locales Iowan Old Style, Palatino o Georgia. Los controles usan la sans del sistema y la fecha y las leyendas recurren a la monoespaciada local. La barra lateral se convierte en dos filas de destinos en teléfono.

El inicio reúne la cola vencida, la proporción histórica de recuerdo y el número de sesiones. Cada cubierta lleva al repaso de su mazo cuando hay tarjetas pendientes. Durante el estudio la pregunta ocupa el centro. Espacio revela el reverso y los números del 0 al 5 envían la calificación. La barra avanza cuando el servidor confirma el envío. El resumen cuenta los recuerdos con nota de 3 a 5.

En el taller se puede crear el mazo y convertir texto en tarjetas. Las plantillas permiten practicar a partir de ejemplos existentes. Fuentes y errores tienen una etapa de revisión antes de incorporarse al mazo. La analítica expresa cada proporción con su denominador y muestra «Sin muestra» cuando todavía no hay observaciones.

## Decisiones derivadas de las skills

| Playbook o skill | Hallazgo | Cambio aplicado |
| --- | --- | --- |
| pstack · feature | Los datos de la cola incluyen la solución y las listas se limitan a 100 elementos. | El transporte pagina las listas. La sesión conserva solo la pregunta y el ID hasta revelar. El taller tiene un propietario y un módulo independiente. |
| emil-design-eng | La acción diaria compite con la gestión de contenido si ambas tienen el mismo peso. | Un único mando ámbar en la carta lunar, cubiertas más discretas y orden de lectura estable. |
| break-ui | Los enteros de 64 bits pierden precisión como números de JavaScript. Los nombres largos compiten con la acción en filas estrechas. | El transporte preserva dígitos y deja intacto el texto entrecomillado. En móvil la acción cae bajo el nombre y las palabras largas pueden partirse. Se probaron 10 000 pendientes, cola vacía, emoji, zoom de texto y pérdida de red. |
| mobile-native | Una barra lateral y controles pequeños reducen el espacio disponible a 320 px. | Navegación en filas, 100dvh, áreas seguras, controles de 44 px y campos de al menos 16 px. |
| find-animation-opportunities | El botón de entrada se usa una vez por sesión. Revelar y calificar se repiten por tarjeta. | Solo la pulsación del acceso principal tiene movimiento. La pregunta, la barra de progreso y los resultados se actualizan de inmediato. |
| animate | La confirmación de pulsación debe poder interrumpirse. | Transición CSS de transform a escala 0,98 en 150 ms y vuelta en 100 ms, con curva cúbica (0,23 / 1 / 0,32 / 1). |
| review-animations | El gesto de puntero no debe alcanzar el foco de teclado ni la preferencia de movimiento reducido. | La transición se limita al puntero fino y a la preferencia de movimiento normal. La presión excluye el foco visible. |

## Límites

El conteo exacto de vencimientos necesita recorrer las páginas de cada mazo. La API entrega tarjetas completas y carece de un contador agregado. En colecciones grandes la latencia depende del número de páginas. El historial agrupa las sesiones según la semántica del servidor. Los segundos de estudio activo no están disponibles. El recorrido móvil se verifica con emulación de navegador; queda pendiente una pasada en Safari de un iPhone físico.
