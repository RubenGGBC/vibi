# Fiabilidad de los turnos de Antigravity

**Fecha:** 8 de agosto de 2026  
**Estado:** diseño aprobado

## Problema

Vibi activa el fallback a Claude cuando pasan veinticinco segundos sin
recibir texto de Antigravity. Los casos reales muestran dos causas distintas:

1. El language server sigue enviando pasos de herramientas, pero
   `agy_client.py` descarta las actualizaciones que no contienen texto. El
   temporizador interpreta trabajo real como silencio.
2. El turno se escribe por el pseudoterminal y se presupone entregado. De forma
   intermitente la CLI no registra ese texto; no aparece un nuevo paso
   `USER_INPUT` y Vibi espera una respuesta a una pregunta que Antigravity
   nunca recibió.

Subir sin más el timeout retrasaría ambos síntomas sin corregirlos.

## Comportamiento aprobado

- Toda actualización nueva de la trayectoria cuenta como señal de vida, aunque
  no contenga texto para locutar.
- El silencio permitido es de veinticinco segundos durante una respuesta normal
  y de sesenta segundos mientras haya una herramienta activa.
- El turno completo conserva el límite absoluto de ciento ochenta segundos.
- Después de teclear, Vibi confirma que aumentó el número de pasos
  `USER_INPUT` de la conversación.
- Si el acuse no aparece, Vibi repite el tecleo una sola vez. Si tampoco se
  registra, falla pronto y usa Claude sin duplicar más intentos.

## Componentes

### `agy_client.py`

`Update` distingue tres datos independientes: texto nuevo, actividad de la
trayectoria y presencia agregada de herramientas en curso. `read_update`
marca actividad cuando `stepsUpdate` contiene pasos. `_iter_updates` entrega
también esos updates sin texto, pero continúa filtrando metadatos ajenos a la
trayectoria.

El cliente añade `user_input_count(cascade_id)`. Usa
`GetCascadeTrajectorySteps` y cuenta los pasos de tipo
`CORTEX_STEP_TYPE_USER_INPUT`. Es una consulta local al language server y no
añade turnos ni modifica la conversación.

### `antigravity_chat.py`

El consumidor reinicia su espera al recibir cualquier `Update` activo. Solo
pasa por `TurnText` los updates cuyo `text` no sea `None`, para que un latido no
borre el texto acumulado.

Antes del tecleo se toma el contador de entradas. Después se consulta hasta que
aumente. El sondeo termina en cuanto aparece el acuse, así que el camino normal
no paga una espera fija. Tras el primer plazo sin acuse se vuelve a teclear una
vez; tras el segundo se corta el cascade y se deja actuar al fallback existente.

El timeout por silencio elegido en cada iteración depende del último estado
agregado de herramientas: veinticinco segundos sin herramientas y sesenta con
alguna en `PENDING` o `RUNNING`. Ningún latido puede superar el tope absoluto de
ciento ochenta segundos.

## Flujo

1. Abrir el stream y esperar a que esté conectado.
2. Consultar cuántos `USER_INPUT` existen.
3. Teclear el turno.
4. Confirmar que el contador aumentó; si no, repetir una vez.
5. Consumir texto y latidos. Los latidos solo renuevan el plazo; no se locutan.
6. Cerrar al final real del iterador o aplicar fallback al superar un límite.

## Errores y seguridad

El reintento está limitado a uno para evitar mensajes duplicados. Una consulta
fallida del contador se considera falta de acuse y sigue el mismo camino
controlado. `ForceStopCascadeTree` se conserva antes del fallback para no dejar
una ejecución huérfana consumiendo cuota.

No se cambia el proveedor de respaldo, el protocolo del frontend ni la forma
de persistir mensajes.

## Pruebas

- Una actualización `SEARCH_WEB/RUNNING` sin texto sale del iterador como
  latido y mantiene el estado de herramienta activa.
- Un latido no altera `TurnText` ni la respuesta final.
- El timeout normal sigue siendo veinticinco segundos.
- Una herramienta activa usa sesenta segundos y el tope total sigue siendo
  ciento ochenta.
- Un tecleo confirmado se envía una sola vez.
- Si el primer tecleo no incrementa `USER_INPUT`, se envía exactamente una vez
  más.
- Dos intentos sin acuse producen `AgyUnavailable` y activan el fallback.
- Las regresiones existentes de avisos intermedios y eco del turno anterior
  continúan pasando.

## Fuera de alcance

- Sustituir siempre el PTY por `SendUserCascadeMessage`, porque añade alrededor
  de dos segundos a todos los turnos.
- Reparar bloqueos internos de una herramienta de Antigravity. Vibi solo
  debe distinguir trabajo vivo de un bloqueo y salir de este último de forma
  acotada.

