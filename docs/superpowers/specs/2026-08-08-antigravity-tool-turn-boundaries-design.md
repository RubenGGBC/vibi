# Límites de turno durante herramientas de Antigravity

**Fecha:** 8 de agosto de 2026  
**Estado:** aprobado

## Problema

Antigravity cierra cada paso de texto con `CORTEX_STEP_STATUS_DONE`. Ese
estado no siempre cierra el turno completo: antes de ejecutar una herramienta,
Gemini puede decir «Ahora te lo busco», cerrar ese paso, ejecutar la búsqueda y
continuar con la respuesta real.

Vibi interpretaba el primer `done` como fin del turno. La petición de voz
terminaba, la cara reactivaba la escucha y la respuesta posterior quedaba en el
stream para el turno siguiente.

## Comportamiento aprobado

El aviso previo se conserva y se locuta de inmediato. Es progreso del mismo
turno, no una respuesta final, por lo que no debe reactivar la escucha.

El turno solo acaba cuando el iterador de actualizaciones de Antigravity se
cierra después de que no quede ninguna herramienta pendiente o en ejecución.
Los `done` individuales siguen sirviendo como fronteras de locución.

## Diseño

`agy_client.py` mantiene el último estado de cada paso de herramienta. Los
pasos de andamiaje (`PLANNER_RESPONSE`, entrada del usuario, historial y
checkpoint) no cuentan como herramientas. Cuando llega un `done` de texto con
alguna herramienta en `PENDING` o `RUNNING`, el cliente continúa leyendo. Al
llegar un `done` sin herramientas activas, cierra el iterador.

`antigravity_chat.py` consume el iterador completo. Emite cada crecimiento del
texto con `boundary=True`, incluido el aviso, pero no vuelve a cortar por
`Update.done`: la autoridad para cerrar el turno es el final del iterador.

El frontend no necesita un evento nuevo. Su cola de locución ya interpreta
`boundary` como final de un bloque dentro del mismo turno y solo reanuda la
escucha cuando `/api/voz` devuelve la respuesta final y termina el stream de
audio.

## Fallos

Los límites existentes se mantienen: un turno tiene un máximo total de ciento
ochenta segundos y un máximo de veinticinco segundos sin actualizaciones. Al
agotarse cualquiera, Vibi corta el cascade y aplica el fallback existente.

## Pruebas

Una prueba del cliente reproduce la traza real aviso → herramienta pendiente →
aviso cerrado → herramienta terminada → respuesta final. Otra prueba del motor
comprueba que `_consume_turn` devuelve la respuesta final y emite tanto el
aviso como la respuesta, sin terminar en el `done` intermedio.

