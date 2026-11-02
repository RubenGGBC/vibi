# Vibi en el móvil Android (versión de prueba) — Diseño

Fecha: 2 de noviembre de 2026.

## Por qué

El usuario quiere usar Vibi sin tocar el móvil cuando no puede ponerse delante
de una pantalla. La escena de referencia es el gimnasio: dice «Vibi», oye un
«ping» en los cascos y pide, por ejemplo, que cambie la canción. La respuesta
llega con la voz de Codex, la misma que ya usa en el escritorio y que le gusta.

Esta versión es **una prueba para ver hasta dónde puede llegar el servicio**. Se
da control total al principio y las limitaciones se decidirán después, con lo
aprendido. Es para el uso del propio usuario en su móvil, no para distribuirla.

## Objetivos

1. Conversar con Vibi por voz desde Android, con la voz Maple de Codex y con
   posibilidad de interrumpirla, también con la pantalla apagada.
2. Controlar YouTube Music, que en este móvil es una APK modificada instalada por
   el usuario. La APK no se modifica: se controla desde fuera con las interfaces
   normales de Android.
3. Controlar el centro de notificaciones: leer, descartar, pulsar botones y
   responder.
4. Controlar cualquier otra app con el móvil desbloqueado, mediante accesibilidad.
5. Seguir pudiendo pedir tareas en los ordenadores a través de Vibi.
6. **Medir** latencias y fallos reales. Sin esas cifras la prueba no sirve.

### Criterios de éxito de la prueba

Son objetivos orientativos, no compromisos; lo obligatorio es medirlos e
informar de ellos.

| Medida | Objetivo |
|---|---|
| Activación → «ping» | < 300 ms |
| Activación → Vibi lista para escuchar | < 2 s |
| Fin de la frase → la canción responde (pausar, siguiente) | < 2 s |
| Fin de la frase → suena una canción concreta | < 4 s |
| Falsos despertares con música y ruido | A observar en una sesión real |
| Autonomía consumida en una hora de gimnasio | A observar |

## Fuera de alcance

- Publicar en Google Play o distribuir a otras personas.
- iPhone y PWA. La PWA no puede escuchar con el móvil bloqueado.
- Gemma u otro modelo local en esta versión. No aporta la voz de Codex. Queda
  como posible respaldo sin conexión más adelante.
- Root y Shizuku.
- Hacer funcionar la voz sin internet o con el servidor apagado.

## Lo que sería un fracaso aunque funcione

- Que suene una voz distinta de la de Codex sin que el usuario lo haya elegido.
- Que Vibi diga que ha hecho algo sin haber recibido el resultado real.
- Que órdenes viejas se ejecuten al reconectar: una «pausa» de hace una hora no
  debe parar la música ahora.
- Que el micro estropee la música durante toda la sesión sin que se pueda
  cambiar de configuración.

## Decisiones del usuario

- La plataforma es **Android**.
- La voz es la de **Codex**, con un **ordenador como servidor**; no hay IA local.
- Hay **control total en la prueba**: sin confirmaciones ni apps bloqueadas,
  bancos y contraseñas incluidos. Se limitará después, cuando se vea el alcance.
- Se controlan **YouTube Music (APK modificada)** y el **centro de
  notificaciones**, además de cualquier otra acción posible.

## Dispositivos de prueba

- **Móvil:** Samsung Galaxy A25. La app debe guiar la exclusión de la optimización de
  batería de One UI y, si está activo, el Bloqueador automático, que puede impedir
  instalar APK.
- **Cascos:** TWS genéricos de modelo desconocido. Se asume Bluetooth clásico, sin LE
  Audio. El gesto solo se usa si llega a Android como botón multimedia; hay que
  comprobarlo en la prueba.
- **Pruebas:** las hace el usuario en el móvil y en el gimnasio.

## Arquitectura

```
Cascos ⇄ App Android ⇄ WebRTC (audio) ⇄ OpenAI
              │
              │ Tailscale: HTTPS (abrir la llamada) + WebSocket de nodo (órdenes)
              ▼
        Servidor Vibi ⇄ Codex app-server ⇄ herramientas ⇄ nodos del PC
```

**Reutiliza lo existente:**

- **Voz:** `app/executors/codex_voz.py` y `POST /api/voz/codex`. El audio no pasa
  por el servidor, que solo negocia el SDP y atiende las herramientas. Referencia
  del cliente: `frontend/src/lib/codexVoice.ts`.
- **Órdenes:** el móvil es **un nodo más** de `app/nodes.py`, conectado a
  `/api/nodos/ws` con su propio token. El token de nodo ya autoriza voz y TTS
  mediante `current_voice_user`, y se puede revocar con
  `POST /api/nodos/{id}/revocar`.
- **Acceso:** Tailscale, ya documentado en el README.
- **Palabra de activación:** la lógica de `vibi-wake`, con Vosk en dos etapas y el
  alias acústico «bibi» (`2026-08-11-vibi-wake-alias-design.md`). Se porta la
  lógica, no el binario de escritorio.

### Recorrido de una orden

1. Codex llama a una herramienta nueva de móvil, declarada en `HERRAMIENTAS`.
2. `SesionVoz._atender` la pasa directamente a `nodes` sin pasar por
   `procesar_mensaje`, para evitar la latencia de un turno completo.
3. El servidor envía la orden al móvil por su WebSocket de nodo; **no** se usa el
   sondeo de 1,5 s de `/api/voz/codex/eventos`.
4. El móvil la ejecuta y devuelve el resultado real.
5. Codex cuenta el resultado. La regla «no anuncies éxito hasta recibirlo» ya está
   en `INSTRUCCIONES`.

**Requisito:** las órdenes de móvil lanzadas por voz **no deben quedar en cola**.
Hoy una orden espera hasta `NODE_ORDER_TTL_SECONDS` (6 horas) si el nodo está
desconectado. Para estas capacidades, si el móvil no está conectado, o la orden no
se ha entregado en unos segundos, debe fallar y caducar para siempre.

### Duración de la llamada y convivencia con el escritorio

Decisiones del autor del diseño, modificables por el usuario:

- **Fin de la llamada:** cuelga al despedirse o tras 10 s de silencio desde la última
  respuesta de Vibi, con ese tiempo configurable. Al colgar, la música y la escucha
  vuelven a su estado anterior.
- **Una llamada por usuario:** se mantiene el límite actual. Una activación del
  escritorio no puede sustituir a una llamada activa del móvil.
- **Conversación:** abrir desde el móvil continúa la conversación activa, sin
  archivarla como hace `/api/voz/abrir` hoy. Así un falso despertar no borra el hilo
  del PC y Vibi recuerda lo anterior entre activaciones.

### Tareas largas en el PC

- La voz no espera a que terminen. Al acabar, el servidor avisa al móvil con un
  mensaje nuevo en el WebSocket de nodo, y este muestra una notificación normal, sin
  hablar sin que se lo pidan.
- Una petición lenta a `vibi_request` no debe bloquear las órdenes del móvil. Hoy
  `lock_herramientas` se retiene durante toda la llamada a la herramienta, y hay que
  corregirlo.

## La app Android

Kotlin nativo, instalada por APK. Un servicio en primer plano de tipo
`microphone` con notificación fija mantiene el WebSocket y la escucha. Android
exige iniciarlo con la app visible, salvo excepciones, así que el usuario lo
enciende al llegar al gimnasio. La notificación lleva un botón de parada que
corta la escucha, la llamada y la ejecución de órdenes.

### Activadores

Se implementan por este orden; cada uno se puede encender y apagar:

1. Botón en la notificación fija: siempre funciona y sirve de base para medir.
2. Gesto de los cascos, si el modelo permite asignarlo.
3. Palabra «Vibi» en el dispositivo.

El «ping» se reproduce **en local en cuanto se detecta la activación**, sin esperar
a que se abra la llamada.

### Micrófono y Bluetooth

Con Bluetooth clásico, usar el micro de los cascos suele bajar la música a calidad
de llamada. Por eso hay ajustes independientes para **escuchar la palabra** y para
**conversar**, cada uno con opción de micro del móvil o de los cascos. La prueba
debe comparar las combinaciones y usar LE Audio si el móvil y los cascos lo
admiten. Mientras dure la conversación es aceptable bajar la música o cambiar de
perfil; al terminar debe volver sola al estado anterior.

### Capacidades

El móvil declara capacidades nuevas en el saludo del nodo y se añaden a
`CAPABILITIES`. En esta prueba **solo se alcanzan desde la llamada de voz**: no se
registran como primitivas de `tools.py`, así que el motor, Telegram y la PWA no las
usan. El móvil queda excluido de la resolución implícita de dispositivo, para que
«ejecuta X» sin nombrar equipo no acabe en él ni provoque «tienes varios
dispositivos».

| Capacidad | Hace | Mecanismo |
|---|---|---|
| `movil.media` | Pausar, reanudar, siguiente, anterior, avanzar, qué suena | `MediaSessionManager` + `MediaController` |
| `movil.media.reproducir` | Poner una canción por búsqueda | Ver más abajo |
| `movil.volumen` | Leer y cambiar el volumen | `AudioManager` |
| `movil.notificaciones.listar` | Leer las notificaciones activas | `NotificationListenerService` |
| `movil.notificaciones.descartar` | Descartar una, o todas las de una app | Ídem |
| `movil.notificaciones.pulsar` | Pulsar un botón | `PendingIntent` de la acción |
| `movil.notificaciones.responder` | Respuesta rápida | `RemoteInput` |
| `movil.apps.abrir` | Abrir una app o un enlace | Intent; ver límites de segundo plano |
| `movil.pantalla.leer` | Árbol de la pantalla actual | `AccessibilityService` |
| `movil.pantalla.actuar` | Tocar, escribir, deslizar, atrás, inicio | `AccessibilityService` |

Android puede exigir que el usuario autorice a mano los «ajustes restringidos»
para los permisos de notificaciones y accesibilidad en una app instalada por APK.
La app debe guiar ese paso.

**Canción concreta.** Probar en este orden y quedarse con el primero que funcione
con el móvil bloqueado:

1. `MediaController.TransportControls.playFromSearch` sobre la sesión de la APK.
2. Buscar el ID con `ytmusicapi` (no oficial) en el servidor y abrir
   `music.youtube.com/watch?v=ID` dirigido al paquete de la APK.

La APK se identifica por su sesión multimedia y queda guardada una vez; **no se
codifica un nombre de paquete**, porque las APK modificadas pueden cambiarlo.

### Control de otras apps

`movil.pantalla.*` se expone como dos o tres herramientas de voz y sigue el mismo
bucle mirar-decidir-actuar que el PC (`2026-08-13-arbol-accesibilidad-design.md`).
Vibi prefiere siempre la capacidad directa cuando existe.

Con el móvil bloqueado no se pueden usar otras apps. Si el usuario activa Extend
Unlock con los cascos como dispositivo de confianza, sí se podría; es un ajuste de
Android y no lo gestiona la app. Si el móvil está bloqueado, la herramienta debe
devolver un error claro para que Vibi lo diga por voz, no fallar en silencio.

## Modo de prueba y permisos

Hoy Vibi no pide aprobación para ninguna orden de nodo: `nodes.clasificar_orden`
devuelve siempre `False` por decisión expresa del usuario del 5 de agosto de 2026, y
el riesgo solo se registra en Actividad. El móvil entra igual, sin una variable ni
un flujo de aprobación nuevos. Limitarlo después será otro diseño; por eso todas las
órdenes siguen pasando por `nodes.dispatch` y dejan su riesgo registrado.

- Las capacidades que traen contenido ajeno (`movil.notificaciones.listar` y
  `movil.pantalla.leer`) se registran en `taint.FUENTES_EXTERNAS` desde el principio.
- **Paso del móvil al PC: sin barrera, por decisión del usuario.** Se le presentó
  una barrera por llamada y eligió no tenerla. Lo leído en el móvil puede acabar en
  `vibi_request`, igual que el resto del contenido externo de Vibi.
- **Riesgo aceptado por el usuario para esta prueba:** un mensaje o una página
  pueden intentar que Vibi actúe en el móvil, incluidos bancos y contraseñas, o que
  ejecute comandos en el PC mediante `shell.run`, y nada lo impedirá por código.
- **Salvaguardas que no limitan la prueba:** cada orden queda en Actividad con su
  origen, y hay parada desde la notificación y revocación del token.

## Instrumentación

Se registran marcas de tiempo por activación: detección, «ping», petición al
servidor, respuesta SDP, conexión WebRTC, primera voz, llamada a herramienta,
envío al nodo, ejecución y resultado. Se amplía la telemetría actual
(`node_dispatch_ms`, `node_execution_ms`) y la app permite exportar una sesión.

## Limitaciones conocidas

- **Servidor encendido:** sin el ordenador y sin su sesión de Codex no hay voz.
- **Superficie experimental y cupo:** la voz realtime del app-server es
  experimental y la cuenta tiene límite de uso (`_marcar_limite`). No hay respaldo
  de voz en esta versión.
- **Arranque de la llamada:** cada llamada lanza un proceso nuevo de Codex. Es el
  retraso más incierto. Si incumple el objetivo, se estudia dejar uno preparado.
- **Latido:** `SIN_LATIDO_S` da la sesión por muerta a los 30 s sin consultar
  eventos, así que el móvil debe seguir consultando también con la pantalla
  apagada, o el servidor debe tomar el latido del WebSocket del nodo.
- **Reinicio:** tras reiniciar hay que desbloquear y abrir la app para reactivarla.

## Primer paso antes de construirlo todo

Hay dos incógnitas que pueden cambiar el diseño. Se resuelven con un prototipo
desechable y se informa de los resultados antes de seguir:

1. Cuánto tarda en abrirse la llamada de Codex desde el móvil por Tailscale.
2. Cómo se comportan los cascos reales: calidad de la música con su micro abierto
   y si se oye la palabra «Vibi» con el micro de los cascos y con el del móvil en
   el bolsillo.

## Lo que se deja al constructor

- Librería de WebRTC y de audio en Android, y versión mínima de Android.
- Formato exacto de argumentos y resultados de cada capacidad.
- Agrupar las capacidades en una herramienta de voz o en varias, según lo que
  mejor elija Codex y lo que menos retrase.
- Portar Vosk o usar otro detector si en Android no da la calidad necesaria.
- Interfaz de la app, que solo necesita ajustes, estado y exportación de medidas.
