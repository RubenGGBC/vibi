# Morgana Desktop Companion: diseño

## Objetivo

Crear una aplicación de Windows que arranque con el sistema, permanezca en la
bandeja y detecte «Morgana» sin enviar audio fuera del PC. Al detectarla,
reproduce una campanita, pausa el detector, muestra la cabeza 3D y mantiene una
conversación por voz hasta que el usuario diga «adiós Morgana», «gracias
Morgana» o pulse la cabeza.

El PC continúa siendo el servidor principal: la aplicación de escritorio vive
en el host Windows y se conecta al FastAPI existente en Docker. Groq y Claude
siguen resolviendo transcripción, conversación y tareas como hoy.

## Arquitectura

La aplicación se implementa con Tauri 2 y reutiliza React, Three.js,
`MorganaFace`, la captura con Web Audio/MediaRecorder y la cola de TTS ya
existentes. La ventana es transparente, sin marco, siempre visible sobre las
demás aplicaciones únicamente durante una conversación, y queda oculta en la
bandeja en reposo.

Un proceso local Python escucha el micrófono con Vosk y el modelo español
`vosk-model-small-es-0.42`. El reconocedor usa un vocabulario limitado a
«morgana» para comportarse como detector de palabra de activación. Vosk y el
modelo tienen licencia Apache 2.0. El proceso acepta órdenes `pause`, `resume`
y `quit` por entrada estándar y emite eventos JSON por salida estándar.

Tauri coordina ambos mundos: inicia el detector, recibe `wake`, reproduce un
sonido nativo, pausa el detector, muestra la ventana y avisa al frontend. Al
cerrarse la conversación oculta la ventana y reactiva el detector.

## Alta y seguridad

En el primer inicio, el usuario introduce la URL local, su nombre y contraseña.
La aplicación usa `POST /api/auth/nodos`, ya existente, y guarda únicamente el
token revocable del nodo. La contraseña no se conserva. El token de nodo solo
se aceptará en los endpoints de voz y TTS; no se convertirá en una credencial
general para archivos, tareas o administración.

FastAPI permitirá los orígenes locales de Tauri y de su servidor de desarrollo.
En reposo, todo el audio se procesa localmente y no se guarda. Solo después de
la activación se envía el turno grabado al endpoint de voz.

## Flujo de conversación

1. En reposo la ventana está oculta y Vosk procesa el micrófono localmente.
2. Al reconocer «Morgana», Tauri pausa Vosk, reproduce la campanita, muestra la
   cabeza y emite `morgana://wake`.
3. El frontend entra en `listening` y graba hasta detectar silencio.
4. El clip se envía a `POST /api/voz` con `conversation_mode=true`.
5. Si la transcripción normalizada es «adiós Morgana» o «gracias Morgana», el
   backend devuelve `via="cerrar"` sin invocar a la IA.
6. En otro caso, Morgana procesa el turno y devuelve su respuesta. La cabeza
   muestra `thinking` y `speaking` mientras se reproduce TTS.
7. Al terminar la locución vuelve automáticamente a `listening`, sin repetir
   la campanita.
8. Un clic sobre la cabeza cancela captura, petición o locución, oculta la
   ventana y reactiva el detector local.

La máquina de estados del frontend es `setup | sleeping | listening | thinking
| speaking | error`. El detector nunca comparte el micrófono con una captura de
conversación y permanece pausado mientras Morgana habla para evitar que se oiga
a sí misma.

## Interfaz

La ventana mide aproximadamente 320 × 360 píxeles, aparece junto a la esquina
inferior derecha, no figura en la barra de tareas y conserva su última posición.
La cabeza 3D domina la ventana. El halo y el estado textual son los únicos
elementos visibles durante la conversación. El gesto distintivo es la aparición
desde la bandeja con el halo de escucha; no se añaden paneles ni decoración
genérica.

El menú de bandeja ofrece: «Despertar a Morgana», «Pausar/reanudar escucha»,
«Abrir Morgana» y «Salir». En el primer inicio la ventana muestra el formulario
de vinculación. Si Docker no responde o el token ha sido revocado, se muestra
una instrucción concreta y la aplicación vuelve a la bandeja sin detenerse.

## Empaquetado y operación

El repositorio incluirá scripts PowerShell para descargar el modelo español y
empaquetar el detector con PyInstaller. Tauri incluirá el ejecutable y el modelo
como recursos del instalador. En desarrollo podrá ejecutar directamente el
script con el Python del sistema.

El autoarranque se registra mediante el plugin oficial de Tauri. Solo se admite
una instancia. Cerrar la ventana la oculta; «Salir» desde la bandeja termina la
aplicación y el proceso de escucha.

## Comprobación acordada

Por petición expresa del usuario no se crearán ni ejecutarán tests automáticos
para esta entrega. La verificación consistirá en comprobación de tipos,
compilación del frontend y de Tauri, arranque manual, alta del nodo, detección
de «Morgana», cierre por frases y clic, y recuperación con Docker detenido.

