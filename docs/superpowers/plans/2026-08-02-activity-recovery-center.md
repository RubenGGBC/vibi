# Activity and Task Recovery Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar a cada usuario una vista privada de actividad y permitir que recupere una tarea fallida mediante un intento nuevo y auditable.

**Architecture:** SQLite pagina los eventos por id y calcula métricas por usuario; un módulo puro convierte el log interno en una proyección pública allowlisted. FastAPI expone esa proyección y reutiliza el orquestador de tareas para reintentos. React Query presenta resumen, filtros y paginación, e invalida los datos ante eventos vivos.

**Tech Stack:** Python 3.12, FastAPI, SQLite, unittest/pytest, React 19, TypeScript 6, TanStack Query, Vitest, Testing Library, CSS.

## Global Constraints

- No se añaden dependencias ni tablas.
- Toda consulta de actividad filtra por `user_id` en SQL.
- Nunca se exponen payloads crudos, rutas absolutas, prompts completos, tokens, claves ni ids de chat.
- Solo las tareas propias en `error` se pueden reintentar.
- Cada reintento crea otra tarea y vuelve a planificación y aprobación.
- La estructura visual de tres columnas y la paleta actual se conservan.

---

### Task 1: Consulta y proyección segura de actividad

**Files:**
- Create: `app/activity.py`
- Modify: `app/db.py`
- Create: `tests/test_activity.py`

**Interfaces:**
- Produces: `db.list_events_for_user(user_id: str, limit: int, before_id: int | None, event_types: tuple[str, ...]) -> tuple[list[dict], int | None]`
- Produces: `db.activity_summary(user_id: str, recent_since: float) -> dict`
- Produces: `activity.CATEGORY_EVENT_TYPES: dict[str, tuple[str, ...]]`
- Produces: `activity.serialize_event(event: dict, user_id: str) -> dict`

- [x] **Step 1: Escribir las pruebas fallidas de aislamiento, cursor y serialización**

```python
def test_list_events_pages_without_crossing_users(self):
    db.log_event("tarea_creada", self.user["id"], task_id="t1", prompt="secreto")
    db.log_event("archivo_subido", self.user["id"], file_id="f1", size_bytes=8)
    db.log_event("tarea_creada", self.other["id"], task_id="foreign")
    first, cursor = db.list_events_for_user(self.user["id"], 1, None, ())
    second, end = db.list_events_for_user(self.user["id"], 1, cursor, ())
    self.assertEqual([row["tipo"] for row in first + second], ["archivo_subido", "tarea_creada"])
    self.assertIsNone(end)

def test_serializer_does_not_expose_internal_payload(self):
    item = activity.serialize_event({"id": 1, "ts": 2, "tipo": "tarea_creada", "payload": '{"task_id":"t1","prompt":"secreto","workspace":"C:/private"}'}, self.user["id"])
    self.assertEqual(item["enlace"], "/tareas/t1")
    self.assertNotIn("secreto", repr(item))
    self.assertNotIn("workspace", repr(item))
```

- [x] **Step 2: Ejecutar el test y confirmar fallo por APIs ausentes**

Run: `python -m pytest tests/test_activity.py -q`
Expected: FAIL porque `app.activity` o `list_events_for_user` todavía no existen.

- [x] **Step 3: Implementar consultas, índice y serializador allowlisted**

```python
CATEGORY_EVENT_TYPES = {
    "tareas": ("tarea_creada", "plan_generado", "tarea_aprobada", "tarea_rechazada", "tarea_completada", "tarea_interrumpida", "tarea_reintentada"),
    "conversacion": ("mensaje", "conversacion_reiniciada"),
    "archivos": ("archivo_subido", "archivo_descargado", "archivo_eliminado"),
    "proyectos": ("proyecto_clonado", "proyecto_eliminado", "proyecto_seleccionado", "seleccion_proyecto"),
    "herramientas": ("herramienta_creada", "tool_invocation_succeeded"),
    "cuenta": ("login_pwa", "login_telegram", "configuracion_ia_actualizada"),
}
```

La consulta pide `limit + 1`, elimina la fila extra y usa el último `id` visible como cursor. `activity_summary` agrega tareas, dispositivos y almacenamiento en consultas confinadas. `serialize_event` parsea JSON con `try/except`, solo usa ids y campos descriptivos permitidos, y verifica ownership antes de producir enlaces de tarea.

- [x] **Step 4: Ejecutar las pruebas del módulo**

Run: `python -m pytest tests/test_activity.py -q`
Expected: PASS.

- [x] **Step 5: Comprobar regresión del backend**

Run: `python -m pytest -q`
Expected: todos los tests pasan.

### Task 2: API de actividad

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `CATEGORY_EVENT_TYPES`, `serialize_event`, `db.list_events_for_user`, `db.activity_summary`
- Produces: `GET /api/actividad?limite=25&antes_de=<id>&categoria=<categoria>`

- [x] **Step 1: Escribir pruebas HTTP fallidas**

```python
def test_actividad_es_privada_paginada_y_sin_payload_crudo(self):
    db.log_event("tarea_creada", self.user["id"], task_id="t1", prompt="secreto", workspace="C:/private")
    db.log_event("login_pwa", self.other["id"], chat_id=999)
    response = self.client.get("/api/actividad?limite=1&categoria=tareas", headers=self.headers)
    self.assertEqual(response.status_code, 200)
    self.assertEqual(len(response.json()["eventos"]), 1)
    self.assertNotIn("secreto", response.text)
    self.assertNotIn("999", response.text)

def test_actividad_rechaza_categoria_desconocida(self):
    response = self.client.get("/api/actividad?categoria=otra", headers=self.headers)
    self.assertEqual(response.status_code, 422)
```

- [x] **Step 2: Ejecutar el test y confirmar 404/ausencia**

Run: `python -m pytest tests/test_api.py -q`
Expected: FAIL porque `/api/actividad` no existe.

- [x] **Step 3: Implementar el endpoint tipado**

```python
CategoriaActividad = Literal["tareas", "conversacion", "archivos", "proyectos", "herramientas", "cuenta"]

@api_router.get("/actividad")
def ver_actividad(limite: int = Query(25, ge=1, le=100), antes_de: int | None = Query(None, ge=1), categoria: CategoriaActividad | None = None, user: dict = Depends(auth.current_user)):
    tipos = activity.CATEGORY_EVENT_TYPES.get(categoria, ()) if categoria else ()
    rows, cursor = db.list_events_for_user(user["id"], limite, antes_de, tipos)
    summary = db.activity_summary(user["id"], time.time() - 120)
    return {
        "resumen": {
            "tareas_activas": summary["active_tasks"],
            "esperando_aprobacion": summary["awaiting_approval"],
            "tareas_completadas": summary["completed_tasks"],
            "almacenamiento_usado_bytes": summary["managed_storage_bytes"],
            "almacenamiento_cuota_bytes": settings.file_user_quota_bytes,
            "dispositivos_conocidos": summary["known_devices"],
            "dispositivos_recientes": summary["recent_devices"],
        },
        "eventos": [
            activity.serialize_event(row, user["id"]) for row in rows
        ],
        "siguiente_cursor": cursor,
    }
```

- [x] **Step 4: Ejecutar pruebas HTTP y backend completo**

Run: `python -m pytest tests/test_api.py -q && python -m pytest -q`
Expected: PASS.

### Task 3: Reintento backend con semántica de nueva tarea

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `tasks.encolar_tarea(user_id, nombre, prompt, workspace, modelo)`
- Produces: `POST /api/tareas/{task_id}/reintentar -> {ok: true, task: Task, source_task_id: str}`

- [x] **Step 1: Escribir pruebas fallidas de estado, ownership y clonación**

```python
def test_reintentar_error_crea_nueva_tarea_por_el_orquestador(self):
    original = db.create_task(self.user["id"], "hazlo", str(self.workspace), "claude-haiku-4-5")
    db.update_task(original["id"], estado="error", resultado="falló")
    with patch("app.api.tasks.encolar_tarea", AsyncMock(return_value={**original, "id": "new", "estado": "pendiente"})) as enqueue:
        response = self.client.post(f"/api/tareas/{original['id']}/reintentar", headers=self.headers)
    self.assertEqual(response.status_code, 201)
    enqueue.assert_awaited_once_with(self.user["id"], "ruben", "hazlo", str(self.workspace), "claude-haiku-4-5")

def test_reintentar_rechaza_tarea_no_fallida(self):
    task = db.create_task(self.user["id"], "hazlo", str(self.workspace))
    self.assertEqual(self.client.post(f"/api/tareas/{task['id']}/reintentar", headers=self.headers).status_code, 409)
```

- [x] **Step 2: Ejecutar y confirmar fallo por endpoint ausente**

Run: `python -m pytest tests/test_api.py -q`
Expected: FAIL con 404.

- [x] **Step 3: Implementar validación y encolado**

El endpoint usa `_owned_task`, exige `estado == "error"`, llama a `encolar_tarea` y traduce `ValueError` de workspace a `409`. Registra `tarea_reintentada` con `source_task_id` y `task_id`; no modifica la tarea original.

- [x] **Step 4: Ejecutar backend completo**

Run: `python -m pytest -q`
Expected: PASS.

### Task 4: Página de actividad

**Files:**
- Create: `frontend/src/pages/ActivityPage.tsx`
- Create: `frontend/src/pages/ActivityPage.test.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/styles/console.css`

**Interfaces:**
- Consumes: `GET /api/actividad`
- Produces: tipos `ActivityCategory`, `ActivityItem`, `ActivitySummary`, `ActivityResponse`
- Produces: ruta `/actividad`

- [x] **Step 1: Escribir prueba de filtros, resumen, enlaces y paginación**

```tsx
it("muestra resumen, filtra y añade eventos anteriores", async () => {
  renderWithClient(<ActivityPage />);
  expect(await screen.findByText("Trabajo activo")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Tareas" }));
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("categoria=tareas"), expect.anything());
  await userEvent.click(screen.getByRole("button", { name: "Cargar anteriores" }));
  expect(await screen.findByText("Plan aprobado")).toBeInTheDocument();
});
```

- [x] **Step 2: Ejecutar y confirmar fallo por componente ausente**

Run: `frontend/node_modules/.bin/vitest.cmd --run src/pages/ActivityPage.test.tsx`
Expected: FAIL porque `ActivityPage` no existe.

- [x] **Step 3: Implementar tipos, consulta incremental y marcado accesible**

La página conserva páginas en estado local por categoría, sustituye el contenido al cambiar filtro y concatena por id al cargar anteriores. Usa `aria-pressed` en filtros, `<time dateTime>`, `<Link>` solo cuando `enlace` existe y `formatBytes` local para la cuota.

- [x] **Step 4: Añadir ruta, navegación y estilos responsive del centro**

Añadir `ActivityPage` a `App.tsx`, un enlace con icono `Activity` al rail y selectores `.activity-*` enfocados en tarjetas, filtros y cronología. Reutilizar tokens `--line` y colores actuales.

- [x] **Step 5: Ejecutar tests, lint y typecheck frontend**

Run: `frontend/node_modules/.bin/vitest.cmd --run`
Expected: PASS.

Run: `frontend/node_modules/.bin/eslint.cmd .`
Expected: exit 0.

Run: `frontend/node_modules/.bin/tsc.cmd --noEmit -p tsconfig.app.json`
Expected: exit 0.

### Task 5: Recuperación en la PWA y refresco en vivo

**Files:**
- Modify: `frontend/src/pages/TaskDetailPage.tsx`
- Modify: `frontend/src/pages/TaskDetailPage.test.tsx`
- Modify: `frontend/src/lib/useEvents.ts`
- Modify: `frontend/src/lib/useEvents.test.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: `POST /api/tareas/{id}/reintentar`
- Produces: botón `Reintentar tarea` para `estado === "error"`

- [x] **Step 1: Escribir pruebas fallidas de navegación e invalidación**

```tsx
it("reintenta una tarea fallida y abre el nuevo intento", async () => {
  // GET devuelve error; POST devuelve task.id = t2.
  await userEvent.click(await screen.findByRole("button", { name: "Reintentar tarea" }));
  expect(await screen.findByText("Nuevo intento")).toBeInTheDocument();
  expect(location.pathname).toBe("/tareas/t2");
});

it("invalida actividad cuando cambia una tarea", async () => {
  const invalidate = vi.spyOn(client, "invalidateQueries");
  applyServerEvent(client, { tipo: "tarea_actualizada", task });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["activity"] });
});
```

- [x] **Step 2: Ejecutar y confirmar ambos fallos de comportamiento**

Run: `frontend/node_modules/.bin/vitest.cmd --run src/pages/TaskDetailPage.test.tsx src/lib/useEvents.test.ts`
Expected: FAIL porque no existe la acción ni la invalidación.

- [x] **Step 3: Implementar mutación, navegación, feedback e invalidación**

Usar `useNavigate`; tras éxito, invalidar `taskKeys.all` y `["activity"]`, escribir la tarea devuelta en su clave de detalle y navegar a `/tareas/<nuevo id>`. El error usa `ApiError`. `applyServerEvent` invalida actividad ante tarea o archivo actualizado/eliminado.

- [x] **Step 4: Ejecutar suite frontend completa**

Run: `frontend/node_modules/.bin/vitest.cmd --run`
Expected: PASS.

### Task 6: Documentación y verificación final

**Files:**
- Modify: `README.md`
- Modify: `docs/diario.md`

**Interfaces:**
- Documents: endpoint, privacidad, filtros, resumen y semántica del reintento.

- [x] **Step 1: Documentar la funcionalidad y decisiones operativas**

Añadir al README una sección «Actividad y recuperación» y al diario una entrada fechada con el índice, proyección allowlisted, paginación y reintentos inmutables.

- [x] **Step 2: Revisar placeholders y whitespace**

Run: `rg -n "TB[D]|TO[D]O|implement lat[e]r|fill i[n]" docs/superpowers/plans/2026-08-02-activity-recovery-center.md docs/superpowers/specs/2026-08-02-activity-recovery-center-design.md`

Run: `git diff --check`
Expected: `rg` sin coincidencias y `git diff --check` exit 0.

- [x] **Step 3: Ejecutar verificación completa fresca**

Run: `python -m pytest -q`
Expected: todos los tests pasan.

Run: `frontend/node_modules/.bin/vitest.cmd --run`
Expected: todos los tests pasan.

Run: `frontend/node_modules/.bin/eslint.cmd .`
Expected: exit 0.

Run: `frontend/node_modules/.bin/tsc.cmd --noEmit -p tsconfig.app.json && frontend/node_modules/.bin/tsc.cmd --noEmit -p tsconfig.node.json && frontend/node_modules/.bin/vite.cmd build`
Expected: exit 0 y bundle generado.

- [x] **Step 4: Revisar el diff contra los ocho criterios de aceptación**

Run: `git status --short && git diff --stat && git diff --check`
Expected: solo archivos del centro de actividad, recuperación, pruebas y documentación; sin errores de whitespace.
