# Morgana 🔮

Asistente personal multi-usuario con agentes de código, autoalojado.
Delega tareas desde cualquier sitio (Telegram, PWA, voz en el lab),
revisa el plan desde el móvil, aprueba, y Morgana trabaja sobre tu código.

> Fase actual: un usuario, Telegram + PWA y dos vías de ejecución.
> El diseño sigue preparado para multiusuario real; ver Roadmap.

## Arquitectura

```mermaid
flowchart TB
    subgraph clientes [Clientes]
        TG[Telegram bot]
        PWA[PWA móvil / PC]
        PI[Pi con voz y cara - fase 3]
    end

    subgraph core [Core - PC servidor, Docker]
        API[FastAPI]
        R{Router Groq}
        RAP[Vía rápida\nGroq chat]
        COLA[Cola de tareas\nplan → aprobación → ejecución]
        AG[Vía agéntica\nClaude Agent SDK]
        DB[(SQLite\nusers / tasks / events)]
    end

    TG --> API
    PWA --> API
    PI -.-> API
    API --> R
    R -->|pregunta| RAP
    R -->|tarea de código| COLA
    COLA --> AG
    AG --> COLA
    COLA -->|notifica plan / resultado| TG
    COLA -->|eventos WebSocket| PWA
    core --- DB
```

**Las dos vías** (decisión de diseño central):

| | Vía rápida | Vía agéntica |
|---|---|---|
| Para qué | preguntas, resúmenes, chat | tareas sobre código/repos |
| Motor | Groq (latencia mínima) | Claude Agent SDK |
| Coste | céntimos | BYOK del usuario |
| Seguridad | n/a | **plan → aprobación humana → ejecución. Push jamás automático.** |

El **router** clasifica cada mensaje con el propio modelo de Groq
(rápido y barato). Ante la duda, vía rápida: fallar hacia el lado
barato y reversible.

**Flujo de una tarea agéntica:**

1. Le escribes a Morgana: *"en mi proyecto X, hazme un plan para la feature Y"*
2. Router → vía agéntica → se encola la tarea
3. El agente analiza el workspace en **modo plan** (solo lectura) y produce un plan
4. Te llega el plan a Telegram con botones **Aprobar / Rechazar**
5. Si apruebas: el agente aplica el plan (`acceptEdits`) en una rama nueva. **Nunca hace push** — eso es siempre tuyo.
6. Te llega el resumen de lo hecho

## Setup

```bash
cp .env.example .env   # y rellena tus claves
docker compose up --build
```

Antes de entrar en la PWA, crea o vincula el usuario con `/start` en
Telegram y fija su contraseña (el nombre es exacto):

```bash
docker compose exec morgana python -m scripts.set_password ruben
```

Configura un `JWT_SECRET` aleatorio de al menos 32 caracteres. La app queda en
`http://localhost:8000/` y Docker solo la publica en loopback por defecto.

Para abrir e instalar la PWA desde el móvil sin exponerla a la LAN, publica el
servicio dentro de tu tailnet y copia la URL HTTPS que muestre el comando:

```bash
tailscale serve --bg http://127.0.0.1:8000
```

Pon esa URL (por ejemplo, `https://mi-pc.mi-tailnet.ts.net`) en
`PWA_BASE_URL` y recrea el contenedor. `MORGANA_BIND_ADDRESS` solo debe cambiarse
si quieres publicar directamente el puerto y ya has resuelto firewall y TLS.

Sin Docker (desarrollo):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Necesitas una key de [Groq](https://console.groq.com) y un bot de
Telegram (créalo hablando con `@BotFather`, copia el token). Para la
vía agéntica puedes elegir entre una key de
[Anthropic](https://console.anthropic.com) o el login de Claude Code
incluido en una suscripción Claude Pro/Max.

### Autenticación de Claude

Morgana acepta tres valores de `CLAUDE_AUTH_MODE`:

| Modo | Comportamiento |
|---|---|
| `auto` | Usa `ANTHROPIC_API_KEY` si existe; si no, el login Pro/Max persistido |
| `api` | Exige `ANTHROPIC_API_KEY` y factura el uso en Claude Console |
| `subscription` | Ignora la API key y usa el login de Claude Code Pro/Max |

Para usar una API key:

```env
CLAUDE_AUTH_MODE=api
ANTHROPIC_API_KEY=sk-ant-...
```

Para usar una suscripción Pro/Max, deja la key vacía, construye la
imagen e inicia sesión una vez:

```env
CLAUDE_AUTH_MODE=subscription
ANTHROPIC_API_KEY=
```

```bash
docker compose build
docker compose run --rm -e ANTHROPIC_API_KEY= morgana claude
```

En el asistente selecciona **Claude App (Pro/Max)**. El login se guarda
en el volumen Docker `claude-config`, así que no hace falta repetirlo
en cada reinicio. Después arranca Morgana normalmente:

```bash
docker compose up -d
```

Abre tu bot, envía `/start` y empieza a hablar.

La opción recomendada es clonar proyectos desde la pantalla **Proyectos** de
la PWA: Morgana los coloca en `workspace/<uuid-del-usuario>/`. Si vas a copiar
uno a mano, consulta primero tu `id` con `GET /api/yo` usando el Bearer JWT y
usa exactamente ese UUID como nombre de carpeta. El nombre visible de Telegram
no se utiliza como ruta.

## Estructura

```
app/
├── main.py               # FastAPI + worker + bot en un proceso
├── config.py             # settings desde .env
├── db.py                 # users, tasks, events (log append-only)
├── auth.py               # bcrypt + JWT compartido por HTTP y WS
├── api.py                # endpoints REST de la PWA
├── events.py             # WebSocket y conexiones por usuario
├── projects.py           # clonado seguro y confinado
├── web.py                # estáticos y fallback del router React
├── router.py             # clasificador rápida/agéntica
├── tasks.py              # orquestador: cola + estados + notificaciones
├── core/
│   └── messages.py       # caso de uso compartido por Telegram y PWA
├── executors/
│   ├── groq_chat.py      # vía rápida
│   ├── groq_speech.py    # voz a texto con Groq Whisper
│   └── claude_agent.py   # vía agéntica (plan/ejecutar)
└── channels/
    └── telegram.py       # notificador + aprobaciones rápidas

frontend/                 # React, Vite, TypeScript, Tailwind y PWA
scripts/set_password.py   # contraseña de un usuario existente
```

Principios de la implementación:

- **El canal no sabe de negocio, el core no sabe de canales.** `tasks.py`
  notifica por callback; Telegram y la PWA renderizan el mismo core.
- **Log de eventos append-only** (`events`): cada mensaje, plan,
  aprobación y resultado queda registrado. Es la base del ángulo de
  investigación (estudio de uso multi-usuario).
- **Tabla `users` desde el día 1**, con hueco para `linux_user`:
  la fase 2 mapea cada usuario a un user de Linux y lanza sus agentes
  con `sudo -u`, aislando workspaces y credenciales por sistema operativo.

## Roadmap

- **Fase 1:** 1 usuario, Telegram, Groq + Claude, aprobación humana
- **Fase PWA (esto):** auth JWT, REST + WebSocket, bandeja, detalle, chat,
  proyectos, deep-links, instalación móvil/PC y conversación táctil en `/cara`
- **Siguiente:** multi-usuario real (users de Linux, secretos por usuario,
  registro), diffs ricos, skills MCP
  activables por usuario, executor CLI (Claude Code / Codex / Gemini
  headless con suscripciones BYO)
- **Fase 3:** la cara — Pi Zero 2 W + HyperPixel Round en el lab,
  wake word, STT Groq Whisper, TTS, login por voz declarativo + NFC,
  memoria de dos niveles (usuario/grupo)

---
*Proyecto personal de Rubén ("Ruffini") — candidato a plataforma del lab ONEKIN.*


## Búsqueda web en la vía rápida

La vía rápida usa `groq/compound-mini` por defecto (1 búsqueda, gasta menos
tokens que `groq/compound` y evita el rate limit de TPM en cuentas
on_demand). Groq decide automáticamente
si una pregunta necesita información actual, noticias, precios, versiones,
normas, horarios o datos poco conocidos y, cuando corresponde, consulta la
web y devuelve citas junto con la respuesta.

Se puede desactivar sin cambiar código:

```env
GROQ_WEB_SEARCH_ENABLED=false
```

## Conversación por voz en `/cara`

La PWA instalada en un móvil o tablet escucha al tocar la cara completa de
Morgana, corta automáticamente tras un breve silencio y envía el clip al
contenedor. FastAPI lo transcribe en español con Groq Whisper y reutiliza el
mismo núcleo de mensajes que el chat. La respuesta se dicta mediante una voz
española del propio dispositivo, priorizando voces femeninas conocidas.

El acceso debe hacerse por **HTTPS** para que Chrome permita usar el micrófono.
El audio se mantiene en memoria durante la petición y no se guarda en disco ni
en SQLite. Estos valores son configurables en `.env`:

```env
GROQ_SPEECH_MODEL=whisper-large-v3-turbo
VOICE_MAX_AUDIO_BYTES=5000000
```

