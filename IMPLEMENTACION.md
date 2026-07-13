# Morgana — implementación desde cero

## 1. Objetivo inicial

Morgana es un asistente personal autoalojado. La primera fase del proyecto define un único cliente (Telegram) y dos vías de trabajo:

- **Vía rápida:** conversación, preguntas y resúmenes mediante Groq.
- **Vía agéntica:** tareas sobre código mediante Claude Agent SDK, con el flujo obligatorio `plan → aprobación humana → ejecución`.

La arquitectura separa el canal de comunicación del núcleo de negocio. Telegram solo recibe mensajes, muestra respuestas y renderiza los botones de aprobación; el núcleo gestiona usuarios, tareas, estados, cola y notificaciones.

## 2. Qué se construyó desde cero

### Configuración

[app/config.py](app/config.py) centraliza la configuración mediante variables de entorno:

- `GROQ_API_KEY` y `GROQ_MODEL`.
- `ANTHROPIC_API_KEY` para el modo API de Claude.
- `CLAUDE_AUTH_MODE` para elegir `auto`, `api` o `subscription`.
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_OWNER_CHAT_ID`.
- `WORKSPACE_ROOT` y `DB_PATH`.

No se guardan claves en el código fuente. `.env` está excluido del control de versiones y del contexto Docker mediante `.gitignore` y `.dockerignore`.

### Base de datos

[app/db.py](app/db.py) crea una base SQLite con tres tablas:

- `users`: identidad, nombre y chat de Telegram.
- `tasks`: prompt, estado, workspace, plan y resultado.
- `events`: log append-only de acciones del sistema.

Los estados de una tarea son:

```text
pendiente
  → planificando
  → esperando_aprobacion
  → ejecutando
  → completada
```

También existen las salidas `rechazada` y `error`.

El contenido de una conversación rápida no se persiste en SQLite. Su historial vive en memoria en la vía Groq. En cambio, las tareas agénticas sí conservan el prompt, plan y resultado.

### Entrada de Telegram

[app/channels/telegram.py](app/channels/telegram.py) implementa:

1. `/start` para crear o vincular el usuario.
2. Recepción de mensajes de texto.
3. Envío de mensajes y respuestas fragmentadas por el límite de Telegram.
4. Botones inline `Aprobar` y `Rechazar`.
5. Registro del canal mediante un callback de notificación.

El canal no decide cómo se ejecuta una tarea: delega esa decisión en el router y en el orquestador.

### Router Groq

[app/router.py](app/router.py) usa Groq como clasificador barato y rápido. Solicita exclusivamente uno de estos JSON:

```json
{"via": "rapida"}
```

```json
{"via": "agentica"}
```

`agentica` se utiliza para cambios, investigación o ejecución sobre repositorios. `rapida` cubre preguntas, conversación, traducciones y resúmenes. Ante un error del clasificador, el sistema cae en `rapida`.

### Vía rápida

[app/executors/groq_chat.py](app/executors/groq_chat.py) mantiene hasta diez turnos por usuario en memoria y envía el historial a Groq junto con la personalidad de Morgana.

Este historial se pierde al reiniciar el proceso; todavía no existe memoria conversacional persistente.

### Orquestador agéntico

[app/tasks.py](app/tasks.py) mantiene una cola `asyncio` y ejecuta el flujo de tareas:

1. Crear la tarea en SQLite.
2. Encolarla.
3. Cambiarla a `planificando`.
4. Pedir a Claude un plan de solo lectura.
5. Guardar el plan y notificarlo por Telegram.
6. Esperar la acción humana.
7. Ejecutar solo después de `Aprobar`.
8. Guardar resultado, error y eventos.

La cola actual vive en memoria; las tareas no se recuperan automáticamente después de reiniciar el servicio.

### Claude Agent SDK

[app/executors/claude_agent.py](app/executors/claude_agent.py) usa dos configuraciones:

```python
ClaudeAgentOptions(
    cwd=workspace,
    permission_mode="plan",
    allowed_tools=["Read", "Glob", "Grep", "Bash"],
)
```

para analizar el workspace, y:

```python
ClaudeAgentOptions(
    cwd=workspace,
    permission_mode="acceptEdits",
    allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
)
```

para aplicar el plan aprobado.

El agente recibe instrucciones de trabajar dentro del workspace, no hacer push y crear una rama nueva cuando se trate de un repositorio Git. El resultado final se devuelve a Telegram.

### API y proceso principal

[app/main.py](app/main.py) arranca en el mismo proceso:

- FastAPI.
- El worker de tareas.
- El bot de Telegram, si existe token.

Los endpoints implementados son:

```text
GET /salud
GET /tareas/{task_id}
```

La PWA todavía no está implementada. Estos endpoints son la base mínima para una futura interfaz web.

## 3. Qué se siguió exactamente del diseño inicial

Se mantuvieron sin cambios de concepto los principios centrales del README original:

- Dos vías de ejecución: Groq para conversación y Claude para código.
- Clasificación mediante un modelo rápido.
- Aprobación humana antes de editar.
- Separación entre canal y core.
- Registro append-only de eventos.
- Tablas de usuarios y tareas preparadas para una futura fase multiusuario.
- Workspaces separados por usuario.
- Ningún push automático.
- Telegram como primer cliente.
- Docker como forma principal de ejecución.

El flujo agéntico sigue siendo exactamente:

```text
mensaje → clasificación → tarea → plan → aprobación → ejecución → resultado
```

## 4. Cambios añadidos sobre la versión inicial

### 4.1. Dos formas de autenticar Claude

Se añadió `CLAUDE_AUTH_MODE`:

| Modo | Comportamiento |
|---|---|
| `auto` | Usa API key si está definida; si no, usa el login persistido de Claude Code |
| `api` | Exige `ANTHROPIC_API_KEY` |
| `subscription` | Ignora la API key y usa el login de Claude Code Pro/Max |

Para API:

```env
CLAUDE_AUTH_MODE=api
ANTHROPIC_API_KEY=sk-ant-...
```

Para suscripción:

```env
CLAUDE_AUTH_MODE=subscription
ANTHROPIC_API_KEY=
```

En modo suscripción se instala Claude Code dentro de la imagen y se persiste su configuración en el volumen Docker `claude-config`.

El login interactivo se realiza con:

```powershell
docker compose run --rm -e ANTHROPIC_API_KEY= morgana claude
```

Después de autenticar la cuenta Pro/Max, Morgana utiliza el Agent SDK con esas credenciales disponibles en el contenedor.

### 4.2. Docker preparado para Claude Code

El [Dockerfile](Dockerfile) ahora instala explícitamente:

- Git.
- Node.js y npm.
- Claude Code CLI.
- Dependencias Python del proyecto.

[docker-compose.yml](docker-compose.yml) añade el volumen persistente:

```yaml
volumes:
  - claude-config:/root/.claude
```

### 4.3. Protección del contexto Docker

Se añadió `.dockerignore` para no enviar al daemon:

- `.env`.
- `.git`.
- `data`.
- `workspace`.
- Cachés de Python.

### 4.4. Logs de Telegram

Las peticiones de Telegram contienen el token del bot en la URL. Se redujo el nivel de logs de `httpx` para que esas URLs no se impriman normalmente:

```python
logging.getLogger("httpx").setLevel(logging.WARNING)
```

### 4.5. Selección dinámica de proyecto

El router ahora extrae, además de la vía, el nombre de proyecto que el usuario menciona en el mensaje (`Clasificacion.proyecto` en [app/router.py](app/router.py)).

[app/tasks.py](app/tasks.py) resuelve ese nombre contra los subdirectorios de `WORKSPACE_ROOT/<user_id>/` (`resolver_proyecto`):

- Coincidencia exacta primero; si no, coincidencia case-insensitive sin ambigüedad.
- Si no menciona proyecto y el usuario tiene más de uno, no asume: pide que elija (`requiere_proyecto`).
- Si no encuentra el nombre, sugiere los más parecidos (`get_close_matches`).
- Todo path resuelto se valida con `resolve()` para que quede dentro de la carpeta del usuario (`validar_workspace_usuario`).

[app/channels/telegram.py](app/channels/telegram.py) añade el comando `/proyectos` (lista los subdirectorios del usuario) y guarda el prompt pendiente en `context.user_data` cuando hace falta preguntar qué proyecto usar, hasta que el usuario responde con el nombre.

## 5. Cómo arrancar

### Con Docker

```powershell
docker compose up --build -d
```

Comprobar el estado:

```powershell
Invoke-RestMethod http://localhost:8000/salud
```

### Conversación rápida

1. Abrir el bot en Telegram.
2. Enviar `/start`.
3. Escribir una pregunta normal.

La ruta será:

```text
Telegram → Router Groq → Groq Chat → Telegram
```

### Tarea agéntica

Crear el repositorio bajo la carpeta que corresponde al nombre del usuario:

```text
workspace/<nombre-en-minusculas>/mi-proyecto/
```

Enviar una petición como:

```text
Analiza mi proyecto y prepara un plan para añadir un endpoint /version.
```

A continuación, revisar el plan y pulsar `Aprobar` o `Rechazar`.

## 6. Verificación realizada

Se verificó que:

- La configuración de Docker es válida.
- Todos los módulos Python compilan sintácticamente.
- La imagen Docker se construye.
- Claude Code está instalado dentro de la imagen.
- El modo `api` selecciona la API key.
- El modo `subscription` evita pasar la API key y deja usar el login persistido.
- FastAPI responde a `/salud`.
- El bot de Telegram arranca correctamente.

No se ejecutó una tarea real de Claude durante la verificación para no modificar un repositorio del usuario ni consumir llamadas innecesarias.

## 7. Límites actuales

La implementación sigue siendo fase 1:

- No hay PWA ni frontend web.
- La cola no sobrevive reinicios.
- El historial rápido no se persiste.
- La API no tiene autenticación.
- El nombre de Telegram se usa directamente para calcular el workspace.
- Las reglas de no hacer push y no salir del workspace dependen en parte de las instrucciones y permisos del agente.
- No hay multiusuario real con usuarios Linux aislados.
- No hay tests automatizados.

Para una primera prueba se recomienda utilizar un repositorio desechable dentro de `workspace`.

### 4.3. Búsqueda web condicional en Groq

La vía rápida puede usar `GROQ_SEARCH_MODEL` (por defecto,
`groq/compound`). Compound decide si necesita buscar en la web y devuelve las
citas en el texto final. `GROQ_WEB_SEARCH_ENABLED=false` hace que el chat use
directamente `GROQ_MODEL`, que también es el fallback si una petición de
Compound falla.

No se necesita un proveedor ni una credencial de búsqueda externa. Morgana no
persiste las búsquedas ni sus resultados: solo conserva en memoria el historial
normal de la conversación. Compound puede aplicar cargos adicionales por uso
de búsqueda.
