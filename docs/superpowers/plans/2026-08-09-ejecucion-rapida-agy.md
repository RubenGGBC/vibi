# Ejecución rápida de aplicaciones con AGY - Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Abrir aplicaciones conocidas mediante una capacidad tipada y auditada sin invocar un modelo para órdenes inequívocas, manteniendo AGY para peticiones ambiguas o compuestas.

**Architecture:** El agente Windows mantiene un catálogo local inmutable y ejecuta `apps.launch` sin aceptar comandos, rutas ni argumentos. Morgana publica esa capacidad como `devices.launch_app`; un reconocedor puro delante del motor conversacional solo la usa con frases completas y seguras. Los resultados terminales se persisten como un turno normal y fuerzan la reconstrucción de contexto del motor en el turno siguiente.

**Tech Stack:** Python 3.11, asyncio, WebSocket persistente, Pydantic, SQLite, unittest, APIs estándar de Windows (`winreg`, `os.startfile`) y procesos con `argv` fijo para aplicaciones empaquetadas.

## Global Constraints

- La petición del usuario nunca se interpola en PowerShell, `cmd.exe` ni otra shell.
- `apps.launch` acepta únicamente un alias o identificador presente en el catálogo local; no admite rutas, argumentos ni elevación.
- La operación pública pasa por `tools.execute` y `nodes.dispatch`, conservando validación, riesgo, política, interruptor remoto y auditoría.
- Una acción interactiva nunca se encola para un nodo desconectado.
- El reconocedor favorece falsos negativos y rechaza peticiones compuestas, negaciones, URLs, rutas, archivos y tools adjuntas.
- `ANTIGRAVITY_EFFORT=medium` y el modelo configurado no cambian.
- El acuse por trayectoria y los clientes MCP solo se sustituyen si una prueba real demuestra mejora y fiabilidad; este plan instrumenta ambos y conserva el comportamiento actual si no hay evidencia.
- El workspace contiene cambios staged previos en nodos, MCP y AGY. No se harán commits parciales que mezclen su autoría; se entregará un diff revisable.
- Baseline reproducido antes de implementar: `test_api` esperaba la firma anterior sin `tool_ids=()` y `test_files_tools` buscaba el blob en `FILE_STORAGE_ROOT` aunque producción ya usa `workspace/.morgana-files`.

---

### Task 0: Reparar la línea base de pruebas

**Files:**
- Modify: `tests/test_api.py:310`
- Modify: `tests/test_files_tools.py:339`

**Interfaces:**
- Consumes: `message_core.procesar_mensaje(..., tool_ids=())` y `files._managed_user_root(user_id)` existentes.
- Produces: una línea base cuyas expectativas reflejan el comportamiento de producción ya presente.

- [ ] **Step 1: Actualizar la expectativa de la API**

```python
procesar.assert_awaited_once_with(
    db.get_user_by_id(self.user["id"]),
    "hola",
    canal="pwa",
    modelo="claude-opus-4-8",
    client_ref=None,
    tool_ids=(),
)
```

- [ ] **Step 2: Hacer que la prueba de publicación observe la ubicación gestionada real**

```python
destination = (
    tasks.directorio_usuario(user_id)
    / files.MANAGED_UPLOADS_DIRECTORY
    / storage_key
)
```

- [ ] **Step 3: Verificar la línea base corregida**

Run: `python -m unittest tests.test_api.ApiTests.test_mensaje_envia_el_modelo_claude_seleccionado_al_core tests.test_files_tools.FilesApiTests.test_publica_blob_antes_de_confirmar_metadatos_y_limpia_si_fallan -v`

Expected: `Ran 2 tests ... OK`.

---

### Task 1: Catálogo local de aplicaciones Windows

**Files:**
- Create: `agent/morgana_node/app_catalog.py`
- Create: `tests/test_app_catalog.py`
- Modify: `agent/morgana_node/client.py:16`

**Interfaces:**
- Produces: `AppEntry`, `CatalogSnapshot`, `ApplicationCatalog`, `catalog.start_background()`, `catalog.launch(query) -> dict`.
- Produces result statuses: `launched`, `not_found`, `ambiguous`, `launch_failed`, `catalog_starting`.
- Later tasks consume `app_catalog.catalog.launch(str)` only; no target path leaves this module.

- [ ] **Step 1: Escribir pruebas fallidas de normalización y resolución**

```python
def test_exact_unique_alias_launches_catalog_target(self):
    launched = []
    catalog = ApplicationCatalog(
        discover=lambda: [AppEntry("app_1", "Spotify", ("spotify",), "shortcut", "spotify.lnk")],
        launcher=lambda entry: launched.append(entry.target),
    )
    catalog.refresh()
    self.assertEqual(catalog.launch("Spótify")["status"], "launched")
    self.assertEqual(launched, ["spotify.lnk"])
```

Add independent cases for a cold catalog, exact ambiguity, partial candidates capped at five, unknown aliases, an opaque id, launcher failure, leading Spanish articles and a query containing a path or command fragment.

- [ ] **Step 2: Ejecutar RED**

Run: `python -m unittest tests.test_app_catalog -v`

Expected: import failure for `morgana_node.app_catalog`.

- [ ] **Step 3: Implementar tipos, snapshot atómico y resolución exacta**

```python
@dataclass(frozen=True, slots=True)
class AppEntry:
    id: str
    label: str
    aliases: tuple[str, ...]
    launch_kind: str
    target: str

@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    ready: bool = False
    entries: tuple[AppEntry, ...] = ()
    refreshed_at: float = 0.0
    error: str = ""
```

`ApplicationCatalog.refresh()` construye toda la tupla fuera del candado y reemplaza una sola referencia al terminar. `launch()` solo ejecuta una coincidencia exacta y única; una coincidencia parcial devuelve etiquetas e ids, nunca targets.

- [ ] **Step 4: Ejecutar GREEN del núcleo**

Run: `python -m unittest tests.test_app_catalog -v`

Expected: todos los casos del catálogo artificial pasan.

- [ ] **Step 5: Añadir descubrimiento Windows con comandos fijos**

Implementar fuentes del menú Inicio, `HKCU/HKLM ... App Paths` y `Get-StartApps` con un `argv` constante. Los ids se derivan con BLAKE2 de `kind + target`; los aliases se normalizan con `casefold`, NFKD, espacios y artículos. En Windows, los `.lnk`/`.exe` se abren con `os.startfile`; las apps empaquetadas con `subprocess.Popen(["explorer.exe", "shell:AppsFolder\\<id>"])`.

- [ ] **Step 6: Probar que el lanzamiento no usa shell ni texto libre**

Add tests that patch `os.startfile`/`subprocess.Popen`, assert exact argv and prove `shell=True` is never supplied. Assert a query like `Spotify & calc.exe` never reaches the launcher.

- [ ] **Step 7: Arrancar el refresco sin bloquear la conexión**

Call `app_catalog.catalog.start_background()` once at the beginning of `client.run_forever`; the call only starts a daemon thread and returns before `_sesion` connects.

---

### Task 2: Capacidad `apps.launch` y primitiva `devices.launch_app`

**Files:**
- Modify: `agent/morgana_node/capabilities.py`
- Modify: `app/nodes.py`
- Modify: `app/tools.py`
- Modify: `tests/test_nodes.py`
- Create: `tests/test_app_launch.py`

**Interfaces:**
- Consumes: `app_catalog.catalog.launch(query)`.
- Produces node capability: `apps.launch` with `{"app": str}`.
- Produces public primitive: `devices.launch_app` with `DeviceLaunchAppArguments(device: str | None, app: str)`.
- Public result keeps `device`, `state`, `message`, `result`, `node_dispatch_ms`.

- [ ] **Step 1: Escribir pruebas fallidas del agente y del servidor**

```python
def test_node_exposes_typed_app_launch(self):
    with patch.object(app_catalog.catalog, "launch", return_value={"status": "launched"}):
        self.assertEqual(
            capabilities.run(self.config, "apps.launch", {"app": "Spotify"})["status"],
            "launched",
        )
```

Add cases that `apps.launch` appears in both capability allowlists, belongs to desktop effects, is not read-only, respects `shell_habilitado`, is never queued offline and records a normal `tool_invocation` through `tools.execute`.

- [ ] **Step 2: Ejecutar RED**

Run: `python -m unittest tests.test_app_launch tests.test_nodes -v`

Expected: missing capability and primitive failures.

- [ ] **Step 3: Implementar el handler del nodo y allowlists**

```python
def _apps_launch(_: NodeConfig, arguments: dict) -> dict:
    app = str(arguments.get("app") or "").strip()
    if not app:
        raise CapabilityError("Falta la aplicación")
    return app_catalog.catalog.launch(app)
```

Register it in `HANDLERS`, `nodes.CAPABILITIES` and `nodes.CAPACIDADES_ESCRITORIO`.

- [ ] **Step 4: Implementar la primitiva pública**

```python
class DeviceLaunchAppArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: str | None = Field(default=None, max_length=120)
    app: str = Field(min_length=1, max_length=200)
```

The handler resolves one device and dispatches `apps.launch` with `queue_if_offline=False`; it measures dispatch with `time.monotonic()` and never accepts another field.

- [ ] **Step 5: Ejecutar GREEN y auditoría**

Run: `python -m unittest tests.test_app_launch tests.test_nodes -v`

Expected: all new launch, risk, remote-disable, offline and audit cases pass.

---

### Task 3: Reconocedor determinista de acciones

**Files:**
- Create: `app/fast_actions.py`
- Create: `tests/test_fast_actions.py`

**Interfaces:**
- Produces: `recognize_launch(text, attached_tool_ids=()) -> LaunchAction | None`.
- Produces: `execute_fast_action(user, action) -> FastActionOutcome`.
- `FastActionOutcome.handled` is true only for `launched`, `ambiguous`, `launch_failed` or a delivered timeout.

- [ ] **Step 1: Escribir el corpus RED**

Use literal table cases. Accepted: `Abre Spotify`, `inicia Visual Studio Code, por favor`, `LANZA la Calculadora`. Rejected: negations, conjunctions, extra actions, URLs, paths, file extensions, quoted arguments, attached tools and empty app names.

- [ ] **Step 2: Ejecutar RED**

Run: `python -m unittest tests.test_fast_actions -v`

Expected: missing module failure.

- [ ] **Step 3: Implementar el parser de frase completa**

Use one anchored regular expression for `abre|inicia|lanza|ejecuta`, strip only terminal punctuation and `por favor`, normalize a leading Spanish article, and reject dangerous/compound tokens before returning `LaunchAction(app=<literal label>)`.

- [ ] **Step 4: Implementar traducción de resultados sin modelo**

Map `launched` to `Abriendo <label>.`, ambiguity to at most five labels, `launch_failed` to an explicit Windows failure and dispatch timeout to the non-duplicating acknowledgement. `not_found`, `catalog_starting`, offline and invalid-device errors return `handled=False` so the full original text reaches the engine once.

- [ ] **Step 5: Ejecutar GREEN**

Run: `python -m unittest tests.test_fast_actions -v`

Expected: corpus, result mapping and “one call only” tests pass.

---

### Task 4: Integrar el carril rápido en `chat.respond`

**Files:**
- Modify: `app/executors/chat.py`
- Modify: `tests/test_antigravity_chat.py`
- Create: `tests/test_fast_chat.py`

**Interfaces:**
- Consumes: `fast_actions.recognize_launch` and `execute_fast_action`.
- Preserves: `ChatResult`, message persistence and all `chat_runtime` events.
- Produces: session invalidation through `engine.close_session(conversation_id)` after a handled action.

- [ ] **Step 1: Escribir integración RED**

Test with a real temporary DB and a minimal fake engine. Assert a handled launch persists user and assistant messages, emits started/message/finished events, never calls `run_turn`, calls `close_session` once, and returns `ChatResult("Abriendo Spotify.")`.

Add separate tests for `not_found` falling through once, a compound request reaching the engine unchanged, ambiguity not invoking the engine, timeout not retrying and attached tools bypassing recognition.

- [ ] **Step 2: Ejecutar RED**

Run: `python -m unittest tests.test_fast_chat -v`

Expected: engine is still called for a simple launch.

- [ ] **Step 3: Reordenar el director del chat**

Inside the existing conversation lock: refresh active conversation, persist the user message, emit start, evaluate the parser before `needs_history`, run the fast primitive when present, otherwise build bootstrap history and call `_run_with_fallback`. Persist the assistant response and always emit finish.

- [ ] **Step 4: Invalidar solo la conversación del motor**

After a handled outcome, call `engine.close_session`; log an exception without turning an accepted launch into a user-visible failure. The next model turn must see both persisted fast messages in `bootstrap_history`.

- [ ] **Step 5: Ejecutar GREEN de integración**

Run: `python -m unittest tests.test_fast_chat tests.test_antigravity_chat -v`

Expected: all fast-path cases and existing fallback/session cases pass.

---

### Task 5: Single-flight, MCP paralelo y salud cacheada de AGY

**Files:**
- Modify: `app/executors/antigravity_chat.py`
- Modify: `app/executors/agy_process.py`
- Modify: `tests/test_antigravity_chat.py`
- Modify: `tests/test_agy_process.py`

**Interfaces:**
- Produces: one per-user `asyncio.Lock` guarding process creation.
- Produces: `AgyProcess.healthy(..., max_age=1.0)` with monotonic success cache.
- Preserves: any stream/send failure abandons and kills the process immediately.

- [ ] **Step 1: Escribir pruebas RED de concurrencia y paralelismo**

Run two `_process_for` calls for one user behind a barrier and assert `AgyProcess.start` is called once. Give Playwright and system MCP two awaitable gates and assert both have started before either is released.

- [ ] **Step 2: Ejecutar RED**

Run: `python -m unittest tests.test_antigravity_chat.ReutilizarElProceso tests.test_antigravity_chat.ArranqueParalelo -v`

Expected: duplicate start and sequential MCP assertions fail.

- [ ] **Step 3: Implementar single-flight y `asyncio.gather`**

Guard the whole health/replacement/start sequence with a per-user lock. Inside the creation branch run:

```python
playwright_url, sistema_url = await asyncio.gather(
    asegurar_playwright(user),
    system_link.asegurar_sistema(user),
)
```

- [ ] **Step 4: Escribir RED de caché de salud**

With a fake monotonic clock, call `healthy()` twice inside one second and assert one language-server request; advance beyond one second and assert a second request. Assert `alive=False` always returns false without using a cached success.

- [ ] **Step 5: Implementar caché corta solo para éxitos**

Store `_healthy_at` after a successful request. Never cache a failure. `kill()` clears the stamp. A stream/open/send failure continues through `abandonar`, which removes and kills the process regardless of cache.

- [ ] **Step 6: Ejecutar GREEN**

Run: `python -m unittest tests.test_agy_process tests.test_antigravity_chat -v`

Expected: single-flight, parallel startup, health cache and existing recovery tests pass.

---

### Task 6: Telemetría por etapas y reglas de AGY

**Files:**
- Create: `app/turn_telemetry.py`
- Create: `tests/test_turn_telemetry.py`
- Modify: `app/fast_actions.py`
- Modify: `app/executors/chat.py`
- Modify: `app/executors/antigravity_chat.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `TurnTelemetry(clock=time.monotonic)` with `mark_duration`, `mark_at`, `finish` and a payload containing only numeric timings and route.
- Required keys: `route_decision_ms`, `session_health_ms`, `stream_open_ms`, `input_ack_ms`, `time_to_first_text_ms`, `tool_running_ms`, `node_dispatch_ms`, `node_execution_ms`, `post_tool_ms`, `total_ms`, `route`.

- [ ] **Step 1: Escribir RED con reloj falso**

Use a literal sequence of monotonic values and assert exact integer milliseconds, absent stages as zero, no wall-clock dependency and no arbitrary payload/text accepted.

- [ ] **Step 2: Ejecutar RED**

Run: `python -m unittest tests.test_turn_telemetry -v`

Expected: missing module failure.

- [ ] **Step 3: Implementar el acumulador y conectar el carril rápido**

Measure recognition alone as `route_decision_ms`; copy dispatch/execution durations from the typed primitive; finish after assistant persistence. Log every turn. Store fast actions as `turno_accion_rapida`; keep only AGY turns over the existing slow threshold in SQLite.

- [ ] **Step 4: Instrumentar AGY sin cambiar su protocolo**

Measure session/health, stream-listening, input acknowledgement, first text, accumulated tool-running time and post-tool response. Keep `GetCascadeTrajectorySteps` acknowledgement unchanged until the separate real trace proves stream acknowledgement reliable.

- [ ] **Step 5: Enseñar a AGY la primitiva segura**

Extend `REGLAS_SISTEMA` with an explicit instruction to use `devices_launch_app` for opening known desktop applications and not `pc_ejecutar`; retain `pc_ejecutar` for tasks not covered by a typed capability.

- [ ] **Step 6: Documentar behavior and operations**

Document accepted phrases, fallback boundary, `apps.launch`, Windows-only inventory, security invariants, telemetry fields and a manual 30-sample benchmark command in `README.md`.

- [ ] **Step 7: Ejecutar GREEN**

Run: `python -m unittest tests.test_turn_telemetry tests.test_fast_actions tests.test_fast_chat tests.test_antigravity_chat -v`

Expected: all timing and integration cases pass.

---

### Task 7: Verificación completa y aceptación real

**Files:**
- Verify all modified source/test/docs files.

**Interfaces:**
- Consumes every task deliverable.
- Produces a reproducible verification report; it does not hide baseline or environment failures.

- [ ] **Step 1: Ejecutar suites focalizadas**

Run: `python -m unittest tests.test_app_catalog tests.test_app_launch tests.test_fast_actions tests.test_fast_chat tests.test_turn_telemetry tests.test_agy_process tests.test_antigravity_chat tests.test_nodes -v`

Expected: zero failures/errors.

- [ ] **Step 2: Ejecutar suite completa**

Run: `python -m unittest discover -s tests -v`

Expected: zero failures/errors.

- [ ] **Step 3: Verificar sintaxis y diff**

Run: `python -m compileall -q app agent/morgana_node tests`

Run: `git diff --check`

Expected: both exit 0.

- [ ] **Step 4: Probar el nodo Windows real**

Restart the installed companion, wait for the node to advertise `apps.launch`, then run one cold lookup, one unknown app, one ambiguous lookup and one known lightweight app. Inspect only redacted logs and confirm no shell command was generated.

- [ ] **Step 5: Medir treinta aperturas calientes**

For 30 accepted launches, record `route_decision_ms`, `node_dispatch_ms`, `node_execution_ms`, `total_ms`; report p50, p95 and max. Acceptance is zero model calls, route p95 under 2 ms, dispatch/acceptance p50 under 300 ms and p95 under 750 ms.

- [ ] **Step 6: Revisar criterios del diseño uno por uno**

Confirm: no model on simple launch; compound text preserved; next model turn gets persisted fast history; no path/argument injection; audit/risk/remote switch retained; one AGY start per user; MCP startup parallel; existing suite green.

