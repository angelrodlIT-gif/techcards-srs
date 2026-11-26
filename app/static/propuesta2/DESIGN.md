# Observatorio de memoria

## Tres conceptos

**Observatorio.** Una estación nocturna con cartas celestes, una luna grabada y mandos ámbar. La cola del día ocupa el primer plano y el resto del historial queda en instrumentos secundarios.

**Herbario.** Un archivo botánico donde cada mazo tiene una cubierta de papel prensado. Funcionaría bien como colección, aunque el siguiente repaso tendría menos protagonismo.

**Mesa de montaje.** Una sala de edición con pistas horizontales para las sesiones. Su gramática depende demasiado del ancho de pantalla.

Elegí el Observatorio. La oscuridad enmarca la pregunta al estudiar y la carta lunar da identidad al inicio incluso cuando la biblioteca está vacía. Las órbitas son ilustraciones decorativas. Todos los contadores se obtienen de la API.

## Plan

El contrato de datos precede al diseño del inicio. La sesión conserva una cola de identificadores y preguntas, la respuesta revelada y las notas confirmadas. Un módulo de transporte conserva los identificadores decimales. El taller puede implementarse independientemente del inicio y la sesión; cada envío se bloquea mientras espera confirmación. La verificación recorre los flujos con SQLite, datos límite y dos tamaños de pantalla.
