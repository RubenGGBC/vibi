# Límites de sesión de voz de Vibi: diseño

## Objetivo

Cada invocación mediante la palabra «Vibi» debe iniciar una conversación
nueva. Vibi conservará el contexto de todos los turnos de esa invocación y
lo archivará al oír «gracias Vibi» o «adiós Vibi». Una invocación
posterior no podrá leer ni continuar el hilo anterior.

El cierre manual de la cara tendrá el mismo efecto que una despedida para no
dejar una sesión abierta accidentalmente.

## Causa del comportamiento actual

El backend mantiene una única conversación activa por usuario y los turnos de
voz usan esa conversación sin indicar a qué invocación pertenecen. El evento de
despertar empieza a grabar inmediatamente y no abre una sesión en el servidor.

El cierre intenta reiniciar la conversación al final. En algunos caminos se
hace mediante una petición en segundo plano cuyo error se descarta. Por tanto,
si el cierre anterior no llega, falla o se solapa con el siguiente despertar,
el primer turno nuevo vuelve a usar la conversación que seguía activa.

## Enfoque elegido

El servidor será la autoridad sobre el ciclo de vida de cada invocación. La app
abrirá explícitamente una sesión de voz antes de escuchar el primer turno y
guardará el `conversation_id` que devuelva el servidor. Todos los clips de esa
invocación enviarán ese identificador.

Se reutilizarán la tabla y el archivado de conversaciones existentes. No se
creará un segundo historial paralelo ni una migración de datos: el identificador
de conversación existente actuará también como identificador de la sesión de
voz.

## API y validación

`POST /api/voz/abrir`, autenticado con el token del nodo, archivará cualquier
conversación activa pendiente, cerrará su sesión viva de Claude y creará una
conversación vacía. La respuesta incluirá el nuevo `conversation_id`.

`POST /api/voz` requerirá un campo multipart `conversation_id` cuando
`conversation_mode=true`. Antes de procesar el audio, el backend comprobará
que ese identificador pertenece al usuario y sigue siendo su conversación
activa. Un identificador ausente, ajeno, archivado o sustituido devolverá un
conflicto y nunca añadirá mensajes al hilo actual.

Los turnos normales de una misma invocación conservarán el mismo
`conversation_id`. La ruta de procesamiento recibirá esa conversación de forma
explícita, de modo que no pueda cambiar silenciosamente a la conversación
activa más reciente durante una petición.

Al reconocer una despedida válida, el backend archivará la conversación de ese
identificador y responderá con `via="cerrar"`. El cierre manual usará una ruta
autenticada con el mismo identificador y será idempotente: cerrar una sesión que
ya no está activa no podrá cerrar la sesión nueva.

## Flujo del cliente de escritorio

1. Tauri reconoce «Vibi», pausa el detector y emite el evento de despertar.
2. El frontend marca la apertura como pendiente y llama a
   `POST /api/voz/abrir`.
3. Solo después de recibir el `conversation_id` activa el micrófono y comienza
   el primer turno.
4. Cada clip de la charla incluye ese `conversation_id`; las sucesivas
   respuestas vuelven a escucha sin abrir otra sesión.
5. «Gracias Vibi», «adiós Vibi» o el cierre manual archivan únicamente
   esa sesión, limpian el identificador local, ocultan la cara y reanudan el
   detector.
6. El siguiente despertar repite el proceso y obtiene otro identificador.

Si la apertura falla, Vibi no empezará a grabar y mostrará el error. Si el
cierre manual falla, la app no lo dará por completado silenciosamente: conservará
el identificador y mostrará una acción reintentable. La despedida hablada se
resuelve y archiva en el backend antes de devolver la respuesta, por lo que no
depende de una segunda petición del cliente.

Las respuestas tardías de una sesión anterior se ignorarán en el cliente y el
servidor rechazará nuevos turnos con su identificador. Así, cancelar una
petición o despertar de nuevo no permite que el hilo viejo contamine el nuevo.

## Persistencia y alcance

Archivar no borra mensajes. Cada conversación completa seguirá disponible en
el almacenamiento y en las vistas históricas que ya consumen conversaciones
archivadas. No se mezclará su contenido en el contexto de la siguiente
invocación.

Este cambio se limita al ciclo de voz de la aplicación de escritorio. No cambia
las frases de activación o despedida, la detección de silencio, la transcripción,
la síntesis de voz ni el comportamiento general del chat escrito.

## Pruebas de aceptación

- Al abrir una primera sesión, dos preguntas consecutivas se guardan bajo el
  mismo `conversation_id` y la segunda puede usar el contexto de la primera.
- Después de «gracias Vibi» o «adiós Vibi», esa conversación queda
  archivada con todos sus mensajes.
- Una segunda invocación obtiene otro `conversation_id` y su primer turno se
  procesa con historial vacío.
- Un turno tardío que lleve el identificador anterior recibe un conflicto y no
  escribe en ninguna conversación.
- El cierre manual solo puede cerrar la sesión cuyo identificador envía.
- Si la apertura falla, el cliente no activa la captura; si el cierre falla, no
  descarta silenciosamente el identificador.

