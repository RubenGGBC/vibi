# Morgana Cara: diseño de conversación por voz

## Objetivo

Convertir la ruta protegida `/cara` en una interfaz táctil de conversación por voz para móviles y tabletas. La experiencia reutilizará la cara animada de `morgana-cara.html`: un toque iniciará la escucha, Morgana enviará la petición a la IA existente y dictará la respuesta con una voz española femenina.

El objetivo inicial de latencia es que Morgana comience a responder entre dos y cinco segundos después de que el usuario termine de hablar en una consulta conversacional corta. Las consultas con búsqueda web pueden tardar más. La primera versión prioriza compatibilidad y claridad de estados; las optimizaciones de streaming quedan fuera de alcance.

## Decisiones

- La PWA seguirá ejecutándose desde el contenedor Docker del PC principal y se abrirá en los dispositivos mediante la URL HTTPS existente.
- El dispositivo capturará el micrófono con `getUserMedia()` y `MediaRecorder`.
- El backend transcribirá el audio en español mediante Groq y `whisper-large-v3-turbo`.
- La transcripción se procesará con el mismo núcleo usado por `POST /api/mensaje`, conservando el router, el historial conversacional y la creación de tareas.
- La respuesta se reproducirá en el dispositivo mediante `speechSynthesis`, priorizando una voz española femenina instalada. Si no se encuentra una coincidencia femenina conocida, se usará la primera voz española disponible.
- MediaPipe no se incorporará: sus tareas de audio clasifican sonidos, pero no ofrecen transcripción de voz. La detección de actividad y silencio se hará con Web Audio API.
- No se ejecutará Whisper localmente en Docker en esta fase. El contenedor coordinará la petición a Groq para evitar modelos pesados y requisitos de CPU o GPU.

## Arquitectura y responsabilidades

### Frontend

`FacePage` será responsable de presentar la cara y coordinar una máquina de estados pequeña. La captura de audio, la detección de silencio y la síntesis de voz se aislarán tras utilidades o hooks con interfaces comprobables, evitando concentrar acceso a APIs del navegador, red y SVG en un único componente.

La cara completa será un control táctil accesible, no solamente sus rasgos interiores. Tendrá semántica de botón, nombre accesible y foco visible. La pantalla mostrará una instrucción o estado breve sin competir visualmente con la ilustración.

### Backend

Se añadirá un endpoint autenticado de voz que acepte un archivo de audio multipart. Validará que el archivo tenga un tipo y tamaño permitidos, lo transcribirá y enviará el texto resultante al núcleo común de mensajes con canal `pwa_voz`.

El endpoint devolverá la transcripción y el resultado normalizado:

- Para vía rápida: texto transcrito y respuesta conversacional.
- Para vía agéntica: texto transcrito e identificador de tarea, junto con una confirmación breve apta para locución.

La lógica de Groq para transcripción vivirá separada del controlador HTTP para poder probarla sin red y cambiar el modelo posteriormente mediante configuración.

## Flujo de interacción

1. En `idle`, un toque sobre cualquier punto de la cara solicita permiso de micrófono e inicia la grabación.
2. La cara pasa inmediatamente a `listening`.
3. Un segundo toque detiene la grabación. También se detendrá automáticamente tras aproximadamente 0,8 segundos de silencio posteriores a voz detectada. Se establecerá además un límite máximo de grabación para evitar capturas accidentales indefinidas.
4. Con audio válido, la cara pasa a `thinking` mientras se sube, transcribe y procesa la petición.
5. Al recibir una respuesta, la cara pasa a `speaking` y el dispositivo reproduce la locución.
6. Al terminar, vuelve a `idle`.
7. Si se toca durante `speaking`, la locución se cancela y comienza una nueva escucha.

La máquina de estados será `idle → listening → thinking → speaking → idle`, con transiciones de error hacia `idle`. Solo habrá una grabación, petición o locución activa a la vez.

## Tratamiento de respuestas

Las respuestas conversacionales se dictarán completas. Cuando el router cree una tarea agéntica, Morgana dirá una confirmación corta que indique que la tarea quedó creada y continuará ejecutándose en segundo plano. La ruta `/cara` no mostrará el historial completo del chat ni una interfaz de gestión de tareas; esas funciones seguirán en sus rutas actuales.

Antes de sintetizar, se limpiarán del texto los elementos de Markdown que resulten incómodos al oído. No se alterará el contenido semántico de la respuesta.

## Errores y recuperación

- Micrófono no disponible o permiso denegado: se mostrará una instrucción clara para habilitarlo y se volverá a `idle`.
- Navegador sin las APIs necesarias: se informará que el dispositivo no admite conversación por voz y no se ofrecerá un control que falle silenciosamente.
- Grabación sin voz o transcripción vacía: Morgana indicará que no ha oído nada y permitirá reintentar con otro toque.
- Audio inválido, excesivo o no admitido: el backend responderá con un error controlado y no enviará nada a la IA.
- Fallo de red, Whisper o IA: se mostrará un mensaje breve, se cancelarán recursos activos y se volverá a `idle`.
- Cambio de ruta o desmontaje: se detendrán pistas del micrófono, temporizadores, contexto de audio y síntesis en curso.

## Experiencia visual

Se trasladará el SVG y los estados visuales de `morgana-cara.html` a React conservando su identidad felina, paleta nocturna y animaciones `idle`, `listening`, `thinking` y `speaking`. La ilustración será el elemento dominante y ocupará una zona táctil amplia adaptada a orientación vertical y horizontal.

La interfaz respetará `prefers-reduced-motion`, áreas seguras del dispositivo, navegación por teclado y lectores de pantalla. El contenido seguirá integrado en la estética actual de Morgana; no se conservarán los botones de demostración de la plantilla.

## Seguridad y límites

- El endpoint exigirá el JWT actual.
- El audio se mantendrá en memoria el tiempo imprescindible y no se guardará en disco ni en SQLite.
- Se aceptarán únicamente formatos producidos por navegadores compatibles y soportados por Groq.
- Se impondrán límites de tamaño y duración coherentes con conversaciones cortas.
- La clave de Groq seguirá exclusivamente en el backend.

## Pruebas y verificación

Las pruebas del backend cubrirán autenticación, validación de archivo, transcripción vacía, respuesta rápida, creación de tarea y fallos del proveedor usando sustitutos locales sin llamadas de red.

Las pruebas del frontend cubrirán las transiciones de estado, inicio y parada por toque, parada automática por silencio, prevención de operaciones concurrentes, selección de voz española, cancelación de locución, tratamiento de errores y limpieza al desmontar. `MediaRecorder`, Web Audio y `speechSynthesis` se sustituirán únicamente en los límites inevitables de JSDOM.

La verificación final incluirá las suites Python y Vitest, compilación de producción, revisión visual responsive y una prueba manual desde la PWA instalada en un dispositivo real mediante HTTPS.

## Fuera de alcance

- Streaming de transcripción o respuesta por fragmentos.
- Wake word y escucha permanente.
- Whisper o TTS ejecutados localmente en el contenedor.
- Un proveedor externo de voz española uniforme.
- Historial de conversación visible dentro de `/cara`.
- Optimización avanzada de latencia más allá del objetivo inicial acordado.
