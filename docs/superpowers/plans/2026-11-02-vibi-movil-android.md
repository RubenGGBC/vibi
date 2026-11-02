# Vibi en Android (versión de prueba) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Una app Android que hable con Vibi con la voz de Codex y controle YouTube Music, las notificaciones y el resto del móvil.

**Architecture:** El móvil es un nodo más de `app/nodes.py` y abre la llamada WebRTC directamente con OpenAI mediante la negociación de `codex_voz`. Codex llama a herramientas `movil_*` en el servidor, que las reenvía al nodo sin cola y devuelve el resultado real.

**Tech Stack:** Python/FastAPI (servidor), Kotlin + Gradle (app), OkHttp, `io.getstream:stream-webrtc-android`, `com.alphacephei:vosk-android`, `ytmusicapi`.

**Spec:** `docs/superpowers/specs/2026-11-02-vibi-movil-android-design.md`

## Global Constraints

- Móvil de prueba: Samsung Galaxy A25 (`galaxy-a25-5g` en la tailnet). `minSdk 31`, `compileSdk 35`.
- Voz predeterminada: `maple` (`codex_voz.VOZ_PREDETERMINADA`). Sin otra voz ni respaldo.
- Colgar al despedirse o tras **10 s** de silencio desde la última respuesta (configurable).
- Ninguna orden de móvil se encola: siempre `nodes.dispatch(..., queue_if_offline=False)`.
- Sin barrera móvil→PC y sin flujo de aprobación nuevo (decisión del usuario).
- `movil.*` solo se alcanza desde la llamada de voz: **no** se registra en `tools.py`.
- La APK de música no se modifica ni se codifica su nombre de paquete.
- Rama `movil-android`; no incluir los cambios sin confirmar que ya hay en `master`.
- Textos de la app en español. Tests Python con `python -m pytest`. Tests Kotlin con `android\gradlew.bat -p android test`.
- SDK en `%LOCALAPPDATA%\Android\Sdk`; JDK en `C:\Program Files\Android\Android Studio\jbr`; `adb` fuera del PATH (`platform-tools\adb.exe`).

## Review Focus

- Móvil desconectado o sin servicio al llamar a una herramienta: Vibi lo dice por voz; la orden nunca revive después.
- Tarea lenta de `vibi_request` en curso y «siguiente canción» a la vez: la canción cambia sin esperar.
- Un falso «Vibi» en el escritorio durante una llamada del móvil: la llamada sigue y el hilo no se archiva.
- Sin música sonando, APK cerrada o móvil bloqueado: error hablado claro, no silencio ni un éxito inventado.
- Red que cae a mitad de llamada (wifi → datos): la app cuelga limpio, restaura el audio y vuelve a escuchar.

---

### Task 1: Capacidades `movil.*` en el servidor

**Files:**
- Modify: `app/nodes.py` (`CAPABILITIES`, `CAPACIDADES_LECTURA`, `CAPACIDADES_ENTRADA`), `app/taint.py`, `app/tools.py` (`resolve_device`)
- Test: `tests/test_movil.py`

**Interfaces:**
- Produces: `nodes.CAPACIDADES_MOVIL: tuple[str, ...]`; `nodes.es_movil(node: dict) -> bool` (verdadero si alguna capacidad declarada empieza por `movil.`).

Capacidades: `movil.media`, `movil.media.reproducir`, `movil.volumen`, `movil.notificaciones.listar`, `movil.notificaciones.descartar`, `movil.notificaciones.pulsar`, `movil.notificaciones.responder`, `movil.apps.abrir`, `movil.pantalla.leer`, `movil.pantalla.actuar`.

- [ ] **Step 1: Crear la rama y escribir los tests fallidos** en `tests/test_movil.py`, sobre `NodeTestCase`: `test_nodo_movil_declara_capacidades` (el saludo conserva las 10), `test_resolve_device_ignora_el_movil` (un PC y un móvil conectados, referencia vacía → devuelve el PC, sin `InvalidToolArguments`), `test_resolve_device_solo_movil` (→ `ToolNotFound`), `test_lectura_marca_taint` (`"devices.movil.notificaciones.listar"` y `"devices.movil.pantalla.leer"` están en `taint.FUENTES_EXTERNAS`).
- [ ] **Step 2: Ejecutar** `python -m pytest tests/test_movil.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar.** `listar`, `pantalla.leer` y el resto de lecturas van a `CAPACIDADES_LECTURA`; `pantalla.actuar` a `CAPACIDADES_ENTRADA`. `resolve_device` filtra `es_movil` solo cuando la referencia está vacía.
- [ ] **Step 4: Ejecutar** `python -m pytest tests/test_movil.py tests/test_nodes.py -v`. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(movil): capacidades del nodo móvil en el servidor`.

### Task 2: Herramientas de voz y llamada desde el móvil

**Files:**
- Modify: `app/executors/codex_voz.py`, `app/api.py`, `tests/test_codex_voz.py` (el falso app-server admite herramientas adicionales)
- Create: `app/movil.py`
- Test: `tests/test_movil.py`

**Interfaces:**
- Consumes: `nodes.es_movil`, `nodes.dispatch`.
- Produces:
  - `codex_voz.HERRAMIENTAS_MOVIL: list[dict]`: `movil_musica(accion, consulta?)`, `movil_volumen(accion, nivel?)`, `movil_notificaciones(accion, app?, id?, boton?, texto?, limite?)`, `movil_abrir(destino)`, `movil_pantalla(accion, objetivo?, texto?)`.
  - `codex_voz.abrir(usuario, conversation_id, sdp, voz, delegar, *, delegar_movil=None, origen="escritorio") -> str`.
  - `codex_voz.llamada_movil_activa(usuario) -> bool`.
  - `movil.ejecutar(user: dict, herramienta: str, argumentos: dict) -> dict`.
  - `POST /api/voz/movil/llamada {sdp, voz}` → `{sdp, voz, conversation_id}` (auth `current_voice_user`).

- [ ] **Step 1: Escribir los tests fallidos:**
  - `test_movil_ejecutar_sin_cola`: nodo desconectado → `{"error": ...}` y ninguna orden en estado `pendiente` en la base de datos.
  - `test_movil_ejecutar_mapea_capacidad`: `movil_notificaciones(accion="listar")` → `movil.notificaciones.listar`; `movil_musica(accion="reproducir")` → `movil.media.reproducir`; el resto de `movil_musica` → `movil.media`.
  - `test_accion_desconocida_devuelve_error`.
  - `test_herramienta_lenta_no_bloquea`: con `vibi_request` bloqueada, `movil_musica` termina antes (hoy `lock_herramientas` lo impide).
  - `test_escritorio_no_sustituye_llamada_movil`: con llamada `origen="movil"` activa, `POST /api/voz/abrir` y `/api/voz/codex` → 409, sin archivar la conversación.
  - `test_llamada_movil_continua_conversacion`: `POST /api/voz/movil/llamada` con hilo activo conserva su `id`; sin hilo, crea uno.
  - `test_sin_movil_no_declara_herramientas`: sin nodo móvil, `dynamicTools` sigue siendo `vibi_request` y `terminar_conversacion`.
- [ ] **Step 2: Ejecutar** `python -m pytest tests/test_movil.py tests/test_codex_voz.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar.** `delegar_movil` se pasa en toda llamada si el usuario tiene un nodo móvil. `lock_herramientas` protege solo la lectura y escritura de `resultados`, no la ejecución; una repetición del mismo `callId` en curso debe esperar a su resultado. Añadir a `INSTRUCCIONES`, solo si hay herramientas móvil: usar `movil_*` para el móvil, sin frase de relleno en acciones rápidas, y contar el error real si falla.
- [ ] **Step 4: Ejecutar** los mismos tests. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(movil): la voz de Codex ordena al móvil sin cola`.

### Task 3: Canción por búsqueda y avisos de tareas

**Files:**
- Modify: `app/movil.py`, `app/nodes.py`, `app/main.py`, `requirements.txt` (`ytmusicapi`)
- Test: `tests/test_movil.py`

**Interfaces:**
- Consumes: `movil.ejecutar`; `tasks.registrar_notificador`.
- Produces:
  - Contrato de `movil.media.reproducir`: entrada `{consulta}` o `{video_id}`; salida `{estado: "ok", ...}` o `{codigo: "no_soportado"}`.
  - `movil.notificar_movil(user_id, texto, task_id, acciones) -> None`, que envía `{"tipo": "notificacion", "texto", "task_id"}` a cada nodo móvil conectado.

- [ ] **Step 1: Escribir los tests fallidos:** `test_reproducir_usa_busqueda_directa` (el nodo acepta `consulta` → no se llama a ytmusicapi), `test_reproducir_recurre_a_video_id` (`no_soportado` → busca y reenvía `video_id`), `test_busqueda_sin_resultados_devuelve_error`, `test_tarea_avisa_solo_a_moviles` (un PC conectado no recibe el mensaje).
- [ ] **Step 2: Ejecutar** y ver FAIL.
- [ ] **Step 3: Implementar.** `ytmusicapi` se importa de forma perezosa, sin cuenta, con `filter="songs"`, y en `asyncio.to_thread`. Registrar `notificar_movil` en `app/main.py` junto a `events.notificar`.
- [ ] **Step 4: Ejecutar** `python -m pytest tests/test_movil.py -v`. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(movil): canción por búsqueda y aviso de tareas terminadas`.

### Task 4: Proyecto Android y cliente de nodo

**Files:**
- Create: `android/` (wrapper de Gradle, `settings.gradle.kts`, `app/build.gradle.kts`, `AndroidManifest.xml`), `android/app/src/main/java/es/vibi/movil/nodo/ClienteNodo.kt`, `nodo/Capacidad.kt`, `ajustes/Ajustes.kt`, `servicio/ServicioVibi.kt`, `ui/MainActivity.kt`
- Test: `android/app/src/test/java/es/vibi/movil/nodo/ClienteNodoTest.kt` (MockWebServer)

**Interfaces:**
- Consumes: el protocolo de `/api/nodos/ws`, que es JSON con estos mensajes:
  - Saludo: `{"tipo":"hola","token","capacidades":[...]}`; respuesta `{"tipo":"conexion_lista"}`.
  - Orden: `{"tipo":"orden","id","capability","arguments"}`.
  - Resultado: `{"tipo":"resultado","id","estado":"ok"|"error","resultado":{...}}`.
  - Latido: `{"tipo":"ping"}`; respuesta `pong`.
  - Aviso nuevo de la Task 3: `{"tipo":"notificacion",...}`.
- Produces:
  - `interface Capacidad { val nombre: String; suspend fun ejecutar(args: JSONObject): JSONObject }`.
  - `class ClienteNodo(url, token, capacidades: List<Capacidad>, onNotificacion: (String) -> Unit)` con `conectar()` y `parar()`.
  - `class ErrorMovil(val codigo: String, mensaje: String) : Exception`, que se devuelve como `estado:"error"` con `{codigo, error}`.
  - `ServicioVibi`, servicio en primer plano de tipo `microphone`.

- [ ] **Step 1: Generar el proyecto mínimo y el wrapper de Gradle** (descarga la distribución). Comprobar con `android\gradlew.bat -p android assembleDebug`. Esperado: `BUILD SUCCESSFUL`.
- [ ] **Step 2: Escribir los tests fallidos:** `saluda_con_token_y_capacidades`, `orden_devuelve_resultado_ok`, `excepcion_devuelve_error_sin_caerse`, `capacidad_desconocida_devuelve_error`, `reconecta_con_backoff_hasta_60s`, `parar_no_reconecta`.
- [ ] **Step 3: Ejecutar** `android\gradlew.bat -p android test`. Esperado: FAIL.
- [ ] **Step 4: Implementar** el cliente y lo demás:
  - `MainActivity`: URL de Tailscale, usuario y contraseña; registra el nodo con `POST /api/auth/nodos`, descarta la contraseña y guarda el token cifrado.
  - Guía de permisos: batería de One UI, ajustes restringidos, notificaciones, micrófono y accesibilidad. Comprueba cada uno y muestra su estado.
  - `ServicioVibi`: notificación fija con **Hablar** y **Parar**. **Parar** cierra llamada, escucha y nodo; no se reinicia solo.
  - Avisos `notificacion`: se muestran como notificación normal.
- [ ] **Step 5: Ejecutar** los tests. Esperado: PASS.
- [ ] **Step 6: Commit** `feat(movil): app Android y cliente de nodo`.

### Task 5: La llamada de voz y el primer punto de control

**Files:**
- Create: `android/app/src/main/java/es/vibi/movil/voz/LlamadaVoz.kt`, `voz/RutaAudio.kt`, `voz/ReglasLlamada.kt`, `medidas/Medidor.kt`, `android/app/src/main/res/raw/ping.ogg`
- Test: `voz/ReglasLlamadaTest.kt`, `medidas/MedidorTest.kt`

**Interfaces:**
- Consumes: `POST /api/voz/movil/llamada`, `GET /api/voz/codex/eventos`, `POST /api/voz/codex/cerrar`.
- Produces:
  - `LlamadaVoz.iniciar(origen: String)` y `colgar()`.
  - `ReglasLlamada` (lógica pura): `debeColgar(ahora, ultimaVozVibi, delegando, usuarioHablando, silencioMs = 10_000)`.
  - `enum MicConversacion { MOVIL, CASCOS }`.
  - `Medidor.marcar(evento: String)` y `exportarJson(): String`. Eventos: `deteccion`, `ping`, `peticion`, `sdp`, `webrtc`, `primera_voz`, `herramienta`, `orden`, `resultado`.

- [ ] **Step 1: Escribir los tests fallidos:** `cuelga_a_los_10s_de_silencio`, `no_cuelga_si_delega`, `no_cuelga_si_el_usuario_habla`, `medidor_calcula_intervalos_en_orden`, `medidor_exporta_sesion_incompleta`.
- [ ] **Step 2: Ejecutar** y ver FAIL.
- [ ] **Step 3: Implementar.**
  - El ping suena en local antes de cualquier petición de red.
  - Oferta SDP con pista de micro y canal `oai-events`, como en `frontend/src/lib/codexVoice.ts`.
  - Eventos cada 1,5 s, que además actúan como latido (`SIN_LATIDO_S`).
  - `RutaAudio` usa `setCommunicationDevice` si el micro es `CASCOS`, y al colgar restaura el dispositivo, el modo de audio y el foco de audio, también ante errores.
  - `vibi/cerrar`, `closed` o caída de red → `colgar()`.
  - En la pantalla: exportar medidas y elegir micrófono.
- [ ] **Step 4: Ejecutar** los tests. Esperado: PASS.
- [ ] **Step 5: Instalar** con `adb install -r android\app\build\outputs\apk\debug\app-debug.apk` y confirmar que **Hablar** arranca una conversación con Maple.
- [ ] **Step 6: Commit** `feat(movil): llamada de voz con Codex y medidas`.
- [ ] **Step 7: PUNTO DE CONTROL con el usuario.** Comprobar en el gimnasio el tiempo de apertura por Tailscale, la voz con pantalla apagada y la calidad de la música con cada micro. Si la apertura supera 2 s, estudiar dejar un proceso preparado antes de seguir. El resultado puede cambiar la Task 9.

### Task 6: Música y volumen

**Files:**
- Create: `android/app/src/main/java/es/vibi/movil/capacidades/Media.kt`, `capacidades/Volumen.kt`, `servicio/OyenteNotificaciones.kt`
- Test: `capacidades/MediaLogicaTest.kt`

**Interfaces:**
- Consumes: `Capacidad`, `ErrorMovil`.
- Produces: `movil.media` (`pausar`, `reanudar`, `siguiente`, `anterior`, `avanzar`, `que_suena`), `movil.media.reproducir`, `movil.volumen` (`leer`, `poner`, `subir`, `bajar`). `elegirSesion(sesiones, paqueteGuardado): Sesion?` en lógica pura.

- [ ] **Step 1: Escribir los tests fallidos:** `prefiere_sesion_guardada`, `sin_guardada_usa_la_que_suena`, `sin_sesiones_lanza_sin_musica`, `volumen_se_limita_al_rango`.
- [ ] **Step 2: Ejecutar** y ver FAIL.
- [ ] **Step 3: Implementar** con `MediaSessionManager.getActiveSessions`, usando `OyenteNotificaciones` como componente autorizado. La primera sesión de música se guarda desde la app con «Usar esta app de música». `reproducir` con `consulta` usa `playFromSearch` y comprueba en 3 s que la sesión cambia; si no, devuelve `no_soportado`. Con `video_id` abre `https://music.youtube.com/watch?v=ID` dirigido al paquete guardado.
- [ ] **Step 4: Ejecutar** los tests. Esperado: PASS.
- [ ] **Step 5: Probar en el A25, bloqueado:** pausar, siguiente y una canción concreta por voz.
- [ ] **Step 6: Commit** `feat(movil): control de música y volumen`.

### Task 7: Notificaciones

**Files:**
- Create: `android/app/src/main/java/es/vibi/movil/capacidades/Notificaciones.kt`, modelo en `capacidades/NotificacionesLogica.kt`
- Modify: `servicio/OyenteNotificaciones.kt`
- Test: `capacidades/NotificacionesLogicaTest.kt`

**Interfaces:**
- Produces: `movil.notificaciones.listar {app?, limite=10}` → `{notificaciones:[{id, app, titulo, texto, hora, botones:[...], admite_respuesta}]}`; `descartar {id | app}`; `pulsar {id, boton}`; `responder {id, texto}`. Códigos de error: `no_encontrada`, `sin_respuesta`, `requiere_desbloqueo`.

- [ ] **Step 1: Escribir los tests fallidos:** `filtra_por_app_y_limite`, `ignora_notificaciones_propias_y_en_curso`, `recorta_texto_largo`, `boton_inexistente_lanza_error`, `sin_remote_input_lanza_sin_respuesta`.
- [ ] **Step 2: Ejecutar** y ver FAIL.
- [ ] **Step 3: Implementar** con `NotificationListenerService`, `Notification.Action.actionIntent` y `RemoteInput`. Los ID son `StatusBarNotification.key`. Si la acción tiene `isAuthenticationRequired` y el móvil está bloqueado, devuelve `requiere_desbloqueo`.
- [ ] **Step 4: Ejecutar** los tests. Esperado: PASS.
- [ ] **Step 5: Probar en el A25, bloqueado,** con una notificación real: leer, responder y descartar.
- [ ] **Step 6: Commit** `feat(movil): centro de notificaciones por voz`.

### Task 8: Abrir apps y controlar la pantalla

**Files:**
- Create: `android/app/src/main/java/es/vibi/movil/capacidades/Apps.kt`, `capacidades/Pantalla.kt`, `capacidades/ArbolPantalla.kt`, `servicio/ServicioAccesibilidad.kt`, `res/xml/accesibilidad.xml`
- Test: `capacidades/ArbolPantallaTest.kt`

**Interfaces:**
- Produces: `movil.apps.abrir {destino}`; `movil.pantalla.leer {}` → `{app, nodos:[{ref, rol, texto, acciones}]}`; `movil.pantalla.actuar {accion: tocar|escribir|deslizar|atras|inicio|recientes, ref?, texto?, direccion?}`. Códigos de error: `bloqueado`, `sin_accesibilidad`, `ref_caducada`.

- [ ] **Step 1: Escribir los tests fallidos:** `serializa_solo_nodos_utiles`, `limita_a_200_nodos`, `ref_caducada_lanza_error`, `resuelve_app_por_nombre_sin_acentos`, `nombre_ambiguo_devuelve_candidatas`.
- [ ] **Step 2: Ejecutar** y ver FAIL.
- [ ] **Step 3: Implementar.** Comprobar `KeyguardManager.isKeyguardLocked` antes de actuar. Las referencias se invalidan cada vez que se lee la pantalla. Para abrir apps desde segundo plano, conceder «mostrar sobre otras apps» si Android lo exige; añadirlo a la guía de permisos de la Task 4.
- [ ] **Step 4: Ejecutar** los tests. Esperado: PASS.
- [ ] **Step 5: Probar en el A25,** desbloqueado y bloqueado: «abre Ajustes y entra en Batería»; bloqueado debe explicar el motivo por voz.
- [ ] **Step 6: Commit** `feat(movil): abrir apps y controlar la pantalla`.

### Task 9: Activadores: botón de los cascos y palabra «Vibi»

**Files:**
- Create: `android/app/src/main/java/es/vibi/movil/activacion/BotonCascos.kt`, `activacion/PalabraVibi.kt`, `activacion/DetectorLogica.kt`, modelo Vosk `vosk-model-small-es-0.42` en assets
- Test: `activacion/DetectorLogicaTest.kt`

**Interfaces:**
- Consumes: `LlamadaVoz.iniciar(origen)`.
- Produces: `DetectorLogica.candidato(texto, confianza): Boolean` y `confirmado(texto): Boolean`, con las reglas de la especificación del alias: candidato con gramática `bibi` y confianza mínima; confirmación que acepta `bibi`, `vibi` y `vivi`. `MicEscucha { MOVIL, CASCOS }`, independiente de `MicConversacion`.

- [ ] **Step 1: Escribir los tests fallidos:** `bibi_confiado_es_candidato`, `baja_confianza_no_despierta`, `confirma_vivi_y_bibi`, `frase_ajena_no_confirma`, `no_despierta_durante_llamada`.
- [ ] **Step 2: Ejecutar** y ver FAIL.
- [ ] **Step 3: Implementar.** Copiar el umbral de confianza del detector de escritorio (`vibi-wake`). La escucha se pausa durante la llamada y vuelve al colgar. `BotonCascos` captura los botones multimedia que lleguen como gesto configurable y muestra en la app el último botón recibido, para descubrir qué envían estos TWS. Cada activador se puede apagar.
- [ ] **Step 4: Ejecutar** los tests. Esperado: PASS.
- [ ] **Step 5: Probar en el A25** con música, ruido y cada combinación de micro. Anotar falsos despertares y autonomía en una hora.
- [ ] **Step 6: Commit** `feat(movil): activación por botón y por la palabra Vibi`.

### Task 10: Guía de prueba y cierre

**Files:**
- Create: `android/README.md`
- Modify: `docs/arquitectura.md`, `docs/diario.md`

- [ ] **Step 1: Ejecutar todo:** `python -m pytest tests/test_movil.py tests/test_codex_voz.py tests/test_nodes.py -v` y `android\gradlew.bat -p android test assembleDebug`. Esperado: PASS y APK generado.
- [ ] **Step 2: Escribir `android/README.md`:** instalación, Bloqueador automático, permisos, cómo arrancar el servidor y Tailscale, y la lista de pruebas con la tabla de criterios de éxito de la especificación.
- [ ] **Step 3: Documentar** el nodo móvil en `docs/arquitectura.md` y añadir entrada en `docs/diario.md`, incluido el riesgo aceptado.
- [ ] **Step 4: Commit** `docs(movil): guía de la versión de prueba`.
