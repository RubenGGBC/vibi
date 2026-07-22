# Selector de modelo Claude

## Objetivo

Permitir elegir el modelo de Claude para cada encargo creado desde la PWA y
usar esa misma elección durante la planificación y la ejecución.

## Alcance

- La Bandeja muestra un selector junto al formulario de «Nuevo encargo».
- Las opciones son Sonnet 5 (`claude-sonnet-5`), Fable 5
  (`claude-fable-5`), Opus 4.8 (`claude-opus-4-8`) y Haiku 4.5
  (`claude-haiku-4-5`).
- Sonnet 5 es el valor inicial y el valor usado para tareas ya existentes.
- La API acepta y valida `modelo` al crear el encargo.
- La tarea guarda el identificador y el ejecutor de Claude lo recibe tanto
  al planificar como al ejecutar.

## Fuera de alcance

La vía rápida de Groq y los encargos de Telegram no cambian en esta entrega.

## Errores y pruebas

La API rechaza identificadores fuera de la lista permitida. Se cubren el
contrato HTTP, la persistencia/propagación al ejecutor y el envío desde la UI.
