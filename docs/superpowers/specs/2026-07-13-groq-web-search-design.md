# Búsqueda web condicional en la vía rápida de Groq

## Objetivo

Permitir que Vibi consulte información actualizada cuando una conversación lo necesite, manteniendo el historial y el flujo de Telegram existentes. La búsqueda será gestionada por Groq Compound, que decide internamente si debe usar su herramienta web y devuelve las citas en la respuesta final.

## Diseño

`app/executors/groq_chat.py` seleccionará `GROQ_SEARCH_MODEL` (por defecto `groq/compound`) para responder cuando `GROQ_WEB_SEARCH_ENABLED=true`. El router seguirá usando `GROQ_MODEL`, porque su clasificación no necesita búsqueda web. Cuando la función esté desactivada, la vía rápida usará siempre `GROQ_MODEL`.

El prompt de Vibi explicará que debe buscar únicamente cuando la respuesta dependa de actualidad, datos verificables o información poco conocida; deberá sintetizar las fuentes y conservar las citas que Groq incluya en el contenido. El contexto conversacional seguirá limitado a diez turnos por usuario.

## Configuración

- `GROQ_WEB_SEARCH_ENABLED`: booleano, activado por defecto.
- `GROQ_SEARCH_MODEL`: modelo Compound, por defecto `groq/compound`.
- `GROQ_MODEL`: permanece como modelo normal y como fallback.

No se añade una API externa ni una clave nueva. La documentación indicará que Compound puede generar cargos adicionales por búsqueda y que la función depende de la disponibilidad de Groq.

## Errores y fallback

Si una petición con Compound falla, Vibi reintentará la misma respuesta con `GROQ_MODEL`, preservando el historial. El error no se propagará al usuario salvo que también falle el modelo normal. Este fallback mantiene operativo el chat, aunque no puede garantizar información en tiempo real cuando Compound no está disponible.

## Verificación

Se probará que:

1. La búsqueda habilitada usa el modelo configurado para Compound.
2. La búsqueda deshabilitada usa el modelo normal.
3. El historial conserva la respuesta que finalmente se entrega.
4. Un error de Compound provoca un único fallback al modelo normal.

La documentación de configuración y límites quedará actualizada junto con el código.

## Referencia externa

La integración sigue la API oficial de Groq Compound y su herramienta de Web Search:

- https://console.groq.com/docs/compound
- https://console.groq.com/docs/tool-use/built-in-tools/web-search
