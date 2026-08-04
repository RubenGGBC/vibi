# Morgana Desktop Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar una aplicación de Windows que despierte con «Morgana», muestre la cabeza 3D y mantenga una conversación de voz hasta una despedida o clic.

**Architecture:** Tauri 2 controla bandeja, autoarranque, ventana y un proceso Python/Vosk local. Un nuevo entrypoint React reutiliza la cara y la voz actuales; FastAPI acepta el token revocable de nodo exclusivamente para voz y TTS.

**Tech Stack:** Tauri 2, Rust, React 19, Vite 8, Three.js, Python 3.11, Vosk, sounddevice, FastAPI.

## Global Constraints

- Windows es la única plataforma objetivo de esta primera entrega.
- El detector de «Morgana» debe funcionar sin red y no guardar audio.
- La campanita solo suena al iniciar la conversación, no entre turnos.
- La conversación termina con «adiós Morgana», «gracias Morgana» o un clic.
- No se añaden ni ejecutan tests automáticos por petición expresa del usuario.
- Se preservan todos los cambios locales existentes que no pertenezcan a esta función.

---

### Task 1: Autenticación limitada para el companion

**Files:**
- Modify: `app/auth.py`
- Modify: `app/api.py`
- Modify: `app/main.py`
- Modify: `frontend/src/types.ts`

**Interfaces:**
- Produces: `auth.current_voice_user(...) -> dict`
- Produces: `POST /api/voz` con `conversation_mode: bool`
- Produces: `VoiceResponse` con variante `{ via: "cerrar"; transcripcion: string; respuesta: "" }`

- [ ] **Step 1:** Añadir `current_voice_user`, que prueba primero un JWT y después `nodes.node_from_token`, y solo usarlo en `/voz` y `/tts`.
- [ ] **Step 2:** Normalizar la transcripción con Unicode y detectar exactamente `adios morgana` o `gracias morgana` antes de invocar `procesar_mensaje`.
- [ ] **Step 3:** Añadir CORS limitado a `http://tauri.localhost` y `http://localhost:1420`.
- [ ] **Step 4:** Ejecutar `python -m compileall app` y confirmar salida sin errores.

### Task 2: Detector local Vosk

**Files:**
- Create: `frontend/src-tauri/wake/wake_listener.py`
- Create: `frontend/src-tauri/wake/requirements.txt`
- Create: `frontend/src-tauri/wake/download-model.ps1`
- Create: `frontend/src-tauri/wake/build-sidecar.ps1`

**Interfaces:**
- Consumes stdin: `pause`, `resume`, `quit`
- Produces stdout JSONL: `{ "type": "ready" | "wake" | "paused" | "error", ... }`

- [ ] **Step 1:** Implementar captura mono PCM16 a 16 kHz con `sounddevice.RawInputStream` y `KaldiRecognizer(model, 16000, '["morgana", "[unk]"]')`.
- [ ] **Step 2:** Detectar «morgana» en resultados parciales/finales con debounce de dos segundos y escribir un evento `wake` por línea.
- [ ] **Step 3:** Liberar el stream al pausar y volver a abrirlo al reanudar para no competir con MediaRecorder.
- [ ] **Step 4:** Añadir descarga de `vosk-model-small-es-0.42.zip` y empaquetado PyInstaller.
- [ ] **Step 5:** Ejecutar `python -m py_compile frontend/src-tauri/wake/wake_listener.py`.

### Task 3: Shell Tauri de Windows

**Files:**
- Create: `frontend/src-tauri/Cargo.toml`
- Create: `frontend/src-tauri/build.rs`
- Create: `frontend/src-tauri/tauri.conf.json`
- Create: `frontend/src-tauri/capabilities/default.json`
- Create: `frontend/src-tauri/src/main.rs`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces events: `morgana://wake`, `morgana://listener-error`
- Produces commands: `end_conversation()`, `manual_wake()`, `set_listener_paused(bool)`

- [ ] **Step 1:** Configurar una ventana `companion` transparente, sin marco, 320 × 360, always-on-top, oculta de la barra de tareas y no visible tras la vinculación.
- [ ] **Step 2:** Crear bandeja con despertar, pausa, abrir PWA y salir; cerrar la ventana debe ocultarla.
- [ ] **Step 3:** Iniciar el detector, leer JSONL en un hilo y, en `wake`, pausar, reproducir `SystemAsterisk`, mostrar/enfocar la ventana y emitir el evento.
- [ ] **Step 4:** Registrar autoarranque y single-instance; al salir enviar `quit` al detector.
- [ ] **Step 5:** Añadir scripts `desktop:dev` y `desktop:build` al paquete frontend.

### Task 4: Cliente React del companion

**Files:**
- Create: `frontend/companion.html`
- Create: `frontend/src/companion-main.tsx`
- Create: `frontend/src/components/CompanionApp.tsx`
- Create: `frontend/src/lib/companionApi.ts`
- Create: `frontend/src/styles/companion.css`
- Modify: `frontend/src/lib/voice.ts`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Consumes: `morgana://wake`
- Consumes: `POST /api/auth/nodos`, `POST /api/voz`, `POST /api/tts`
- Produces: llamadas Tauri `end_conversation` y `set_listener_paused`

- [ ] **Step 1:** Añadir formulario inicial que registra el nodo, guarda URL/token y olvida la contraseña.
- [ ] **Step 2:** Implementar estados `sleeping`, `listening`, `thinking`, `speaking`, `error` reutilizando `MorganaFace` y `startVoiceCapture`.
- [ ] **Step 3:** En `wake`, comenzar escucha; tras silencio enviar audio con `conversation_mode=true`; si `via=cerrar`, terminar.
- [ ] **Step 4:** Reproducir TTS completo y volver automáticamente a escuchar cuando finalice.
- [ ] **Step 5:** Hacer que cualquier clic en la cabeza cancele recursos, oculte la ventana y reanude Vosk.
- [ ] **Step 6:** Añadir `companion.html` como entrada Vite y mantener la PWA existente intacta.

### Task 5: Instalación y documentación

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Produces: procedimiento reproducible de instalación en el PC servidor.

- [ ] **Step 1:** Documentar instalación de Rust, dependencias Python, descarga del modelo, modo desarrollo e instalador.
- [ ] **Step 2:** Ignorar modelo, binarios, `target/` y artefactos visuales `.superpowers/`.
- [ ] **Step 3:** Compilar frontend con `npm run build` y Tauri con `npm run desktop:build`.
- [ ] **Step 4:** Verificar manualmente vinculación, palabra de activación, campanita, conversación continua, ambas despedidas, clic y recuperación sin Docker.

