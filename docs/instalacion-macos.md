# Instalar Vibi en macOS (backend local + app nativa de escritorio)

Guía paso a paso para dejar Vibi corriendo en un Mac **sin Docker**: backend
en un venv, PWA/companion compilados con Tauri, agente de nodo para que Vibi
vea ese Mac, y voz. Pensada para que otro agente (u otra persona) la siga sin
tener el resto de la conversación donde se escribió.

Todo lo marcado **(ya en el repo)** es un fix que ya está en `main`/en esta
rama — no hay que tocar código, solo seguir el paso. Lo marcado **(por
máquina)** hay que repetirlo en cada Mac nuevo porque es artefacto local,
credencial o instalación del sistema, no algo que viva en git.

## 0. Requisitos del sistema

- Xcode Command Line Tools: `xcode-select -p` (si no sale ruta, `xcode-select
  --install`).
- Homebrew instalado.
- Python 3.11+ (`python3 --version`).
- Node.js y npm (`node --version`).
- Rust/Cargo — **instálalo con Homebrew, no con `curl | sh` de rustup.app**:

  ```bash
  brew install rust
  ```

  Aviso real que nos pasó: `brew install rust` puede subir la versión de
  `llhttp` (dependencia compartida) y dejar el `node` de Homebrew sin arrancar
  (`Library not loaded: .../libllhttp.9.3.dylib`). Si `node --version` falla
  después de instalar Rust:

  ```bash
  brew reinstall node
  ```

## 1. Clonar y entrar en la rama

```bash
git clone https://github.com/RubenGGBC/vibi.git
cd vibi
git checkout especializacion-por-usuario   # o la rama que toque
```

## 2. Backend Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`vosk` (para el detector de voz) se instala aparte más abajo, no está en este
`requirements.txt` general.

### 2.1 `.env`

```bash
cp .env.example .env
```

Edítalo:

- **`GROQ_API_KEY`** — imprescindible para que haya chat (chat rápido, router,
  Whisper). Gratis en console.groq.com.
- **`JWT_SECRET`** — el backend se niega a arrancar con el valor de ejemplo.
  Genera uno de verdad:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- **`TELEGRAM_BOT_TOKEN`** — el backend también se niega a arrancar si lleva
  el token de ejemplo (`123456:ABC...`) y falla al validarlo contra Telegram.
  Dos opciones: pon un token real de @BotFather, o **déjalo vacío** para
  arrancar sin bot (solo API/PWA/companion).
- **`VIBI_BIND_ADDRESS`** y **`WORKSPACE_HOST_PATH`** — son variables
  *solo para docker-compose*. El modelo `Settings` de Pydantic las rechaza
  (`extra_forbidden`) si están presentes al arrancar sin Docker. **Coméntalas**
  (`#` delante) si vas a correr `uvicorn` directamente.
- **`PLAYWRIGHT_MCP_BROWSER_PATH`** — ruta a un navegador basado en Chromium
  instalado en ese Mac (Chrome, Edge, Opera, Brave — Safari no vale). Ejemplo
  con Chrome:
  ```
  PLAYWRIGHT_MCP_BROWSER_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
  ```
  Sin esto, el nodo no puede abrir el navegador visible y Vibi avisa "No sé
  qué navegador abrir" en el log.
- **`ANTHROPIC_API_KEY`** — opcional. Con `CLAUDE_AUTH_MODE=auto` (por
  defecto) y esta vacía, Vibi usa el login de Claude Code (`claude` CLI) si
  está logueado en esa cuenta de sistema. Sin key y sin login de Claude Code,
  el motor Claude falla — usa `agy` (ver más abajo) o añade la key.

### 2.2 Crear un usuario

El script pide la contraseña con `getpass`, que **necesita una terminal de
verdad** (no vale ejecutarlo sin TTY interactiva):

```bash
.venv/bin/python -m scripts.create_user <nombre> --admin
```

### 2.3 Arrancar el backend

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Comprueba en el log que dice `Application startup complete` y no hay
`ValidationError` (→ revisa el `.env`, sección 2.1) ni `RuntimeError:
JWT_SECRET...` ni `InvalidToken` de Telegram.

## 3. Frontend / PWA

```bash
cd frontend
npm install
```

## 4. App nativa de escritorio (Tauri) para Mac

**(ya en el repo)** El backend ya declara el origen correcto de macOS en CORS
(`app/main.py`, `tauri://localhost` además de `http://tauri.localhost`), y
`frontend/src-tauri/tauri.conf.json` ya usa `"targets": "all"` en vez de
forzar el instalador NSIS de Windows — la config específica de cada
plataforma vive en `tauri.macos.conf.json` / `tauri.windows.conf.json`, que
Tauri fusiona solo. El permiso de micrófono (`NSMicrophoneUsageDescription`)
también está ya en `frontend/src-tauri/Info.plist`. No hay que tocar nada de
esto, solo compilar:

```bash
cd frontend
npm run desktop:build
```

Genera:
- `frontend/src-tauri/target/release/bundle/macos/Vibi.app`
- `frontend/src-tauri/target/release/bundle/dmg/Vibi_1.0.0_aarch64.dmg`

Con el backend corriendo (paso 2.3), abre el `.app` y entra con el usuario
del paso 2.2.

### 4.1 Atajo de teclado para despertar a Vibi

**(ya en el repo)** En Mac es **Command (⌘) sostenido ~400ms** (equivalente al
Alt sostenido de Windows), implementado con `CGEventSourceKeyState` de Core
Graphics en `frontend/src-tauri/src/main.rs`. La primera vez que se use,
macOS puede pedir permiso de Accesibilidad o Monitorización de entrada para
Vibi en Ajustes del Sistema.

## 5. Voz (detector "Vibi" por micrófono) — **(por máquina)**

El binario compilado y el modelo de voz están en `.gitignore`
(`frontend/src-tauri/wake/{dist,models,build}`), así que hay que generarlos
en cada Mac.

```bash
cd frontend/src-tauri/wake

# Modelo de voz en español
mkdir -p models && cd models
curl -L -o vosk-model-small-es-0.42.zip \
  https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
unzip -q vosk-model-small-es-0.42.zip
rm vosk-model-small-es-0.42.zip
cd ..

# Entorno para compilar el sidecar
python3 -m venv .venv
# vosk==0.3.45 (la del requirements.txt) puede no tener wheel para tu Python/
# arquitectura todavía; si falla, usa la última que sí resuelva (0.3.44 en
# Python 3.14/arm64 cuando se escribió esto):
.venv/bin/pip install vosk==0.3.44 "sounddevice>=0.5,<0.6" "pyinstaller>=6,<7"

# Compilar. OJO: --collect-binaries vosk NO coloca bien libvosk.dyld en Mac
# (el import falla con "cannot load library .../libvosk.dyld"); hay que forzar
# la ruta destino a mano con --add-binary:
rm -rf build dist *.spec
.venv/bin/python -m PyInstaller \
  --noconfirm --clean --onefile \
  --name vibi-wake \
  --add-binary ".venv/lib/python3.14/site-packages/vosk/libvosk.dyld:vosk" \
  --distpath dist --workpath build --specpath . \
  wake_listener.py
```

(Ajusta `python3.14` en la ruta de `--add-binary` a la versión real de tu
venv.)

Verifica que arranca antes de seguir:

```bash
./dist/vibi-wake --model models/vosk-model-small-es-0.42 &
sleep 3; kill %1
# debe haber escrito {"type": "ready"} en algún momento (usa un archivo de
# log si lo lanzas en background, ver nota más abajo)
```

Vuelve a compilar la app de escritorio (paso 4) para que el `.app` incluya el
binario y el modelo dentro de `Contents/Resources/wake/` — la fusión ya está
declarada en `tauri.macos.conf.json`, solo hace falta que los archivos
existan cuando se compila.

Sin voz por defecto en `agy`: al abrir el canal de voz Vibi *no* monta el
motor hasta que llega audio de verdad — no hace falta preocuparse por eso.

## 6. Agente de nodo — **(por máquina)**

Le da a Vibi acceso al Mac real: navegador, disco, portapapeles. Sin esto,
cualquier tarea que necesite el ordenador falla con "dispositivo no
conectado".

```bash
cd agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**(ya en el repo)** `agent/requirements.txt` ya fija `mcp>=1.29,<2` (la 2.x
renombra `FastMCP`→`MCPServer` y rompe el servidor de disco de este agente
con "No module named 'mcp.server.fastmcp'"; si ves ese error, `pip show mcp`
y confirma que no se coló una 2.x).

Alta del nodo — pide usuario/contraseña de Vibi por `getpass`, necesita
terminal real:

```bash
.venv/bin/python -m vibi_node registrar --url http://127.0.0.1:8000 --usuario <nombre>
```

Guarda el token en `~/.vibi/node.json` (permisos `0600`). Arrancarlo:

```bash
.venv/bin/python -m vibi_node
```

Se reconecta solo si se cae la red. Para que arranque con el sistema, hay que
envolverlo en un `launchd` (no incluido aquí; ver README para la versión
Windows con Tarea Programada como referencia del patrón).

**Reinicia el backend** (paso 2.3) después de que el nodo se conecte por
primera vez: el backend cachea en memoria si hay dispositivo disponible por
usuario, y no vuelve a comprobarlo a media sesión ya en marcha.

## 7. Motor de chat: Claude vs `agy` (Antigravity/Gemini)

Por defecto el chat usa Claude vía `claude-agent-sdk`, que necesita o bien
`ANTHROPIC_API_KEY` en el `.env`, o bien el `claude` CLI instalado y logueado
(`npm install -g @anthropic-ai/claude-code && claude login` — hecho también
en terminal real).

Para usar `agy` (Gemini) en su lugar:

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
~/.local/bin/agy   # login interactivo (TTY real), guarda su sesión solo
```

Opcional pero recomendable — ponlo explícito en `.env` porque el proceso de
`uvicorn` no siempre hereda `~/.local/bin` en el `PATH`:

```
AGY_BINARY=/Users/<tu-usuario>/.local/bin/agy
```

Modelo (opcional, si no lo pones usa el de la CLI):

```
ANTIGRAVITY_MODEL=gemini-3.6-flash-low
```

(`~/.local/bin/agy models` lista los identificadores válidos — cambian solos
cuando sale un modelo nuevo, no te fíes de una lista escrita en un doc.)

El motor se elige **por usuario**, no en `.env`. Con el usuario ya logueado
en la PWA/companion, cambia `chat_provider` a `antigravity` desde Ajustes en
la propia interfaz, o por API:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Origin: tauri://localhost" -H "Content-Type: application/json" \
  -d '{"nombre":"<nombre>","contraseña":"<contraseña>"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s -X PUT http://127.0.0.1:8000/api/configuracion/ia \
  -H "Authorization: Bearer $TOKEN" -H "Origin: tauri://localhost" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_provider": "antigravity", "chat_model": "claude-haiku-4-5",
    "tools_provider": "anthropic", "tools_model": "claude-haiku-4-5",
    "speech_provider": "groq", "speech_model": "whisper-large-v3-turbo",
    "agent_provider": "anthropic", "agent_model": "claude-sonnet-5"
  }'
```

(`agent_provider` solo admite `"anthropic"` — la vía "agente"/tareas de
código siempre usa Claude, elijas lo que elijas para el chat normal.)

## 8. Fixes ya aplicados al código (para que no se repita el diagnóstico)

Si estás mirando un fallo de estos, ya está resuelto en el repo — comprueba
que tu checkout está actualizado antes de perder tiempo diagnosticándolo de
nuevo:

- **CORS bloqueaba todo desde el `.app` de Mac** (`OPTIONS ... 400`, cualquier
  llamada fallaba): `app/main.py` no declaraba `tauri://localhost` (el origen
  real del WKWebView en macOS) en `allow_origins`, solo el de Windows
  (`http://tauri.localhost`). Arreglado.
- **"Credenciales inválidas" con la contraseña correcta**: un espacio suelto
  al principio del campo "Nombre" (autocompletar, un despiste) hacía que
  `get_user_by_nombre` no encontrara a nadie. `app/api.py` ahora hace
  `.strip()` antes de buscar.
- **Los mensajes de chat fallaban con `CLIConnectionError: Failed to start
  Claude Code: 'NoneType' object is not a mapping`**: con
  `CLAUDE_AUTH_MODE=auto` y sin ninguna API key configurada,
  `app/executors/claude_agent.py` mandaba `env=None` al SDK, que hace
  `**options.env` sin comprobar `None`. Arreglado a `env=env` (diccionario
  vacío, no `None`).
- **Compilar `desktop:build` fallaba con `resource path
  'wake/dist/vibi-wake.exe' doesn't exist`**: la config de `tauri.conf.json`
  era Windows-only (targets `nsis`, recursos con `.exe`). Separado en
  `tauri.macos.conf.json` / `tauri.windows.conf.json`.
