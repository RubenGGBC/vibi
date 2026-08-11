# Tool Workbench 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir el catálogo de herramientas en un workbench extensible por esquema, con nuevas primitivas seguras, ciclo de vida editable e historial personal.

**Architecture:** El registro Pydantic de `app/tools.py` continúa siendo la única lista permitida de capacidades y publica los contratos que consumirá React. La persistencia añade operaciones explícitas de actualización y agregación, mientras los endpoints aplican autorización mediante el servicio de tools. La interfaz usa componentes locales guiados por JSON Schema para no codificar cada primitiva nueva.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite, React 19, TypeScript, TanStack Query, Vitest.

## Global Constraints

- No ejecutar código arbitrario, shell ni URLs suministradas por una tool.
- Todos los datos y efectos deben estar confinados al usuario autenticado.
- No almacenar argumentos ni resultados de invocación.
- Conservar todos los IDs y endpoints existentes.
- Preservar compatibilidad de tools existentes con skills.

---

### Task 1: Primitivas seguras y presets parciales

**Files:**
- Modify: `tests/test_files_tools.py`
- Modify: `app/files.py`
- Modify: `app/tools.py`

**Interfaces:**
- Produces: `files.create_text_file(user_id: str, name: str, content: str) -> dict`
- Produces: `tools.validate_bound_arguments(primitive: Primitive, arguments: dict) -> dict`
- Produces: primitives `tasks.list`, `projects.list`, `activity.recent`, `files.create_note`

- [ ] **Step 1: Write failing service and API tests** covering isolated task/project/activity lists, atomic managed note creation, partial preset acceptance and required runtime fields.
- [ ] **Step 2: Run** `python -m pytest tests/test_files_tools.py -q` **and confirm failures identify the missing primitives and partial validation.**
- [ ] **Step 3: Implement `create_text_file`** with `_safe_name`, UTF-8 bytes, existing size/quota errors, UUID storage key, SHA-256, temporary `xb` file, `os.replace`, DB registration and cleanup on failure.
- [ ] **Step 4: Implement typed argument models and handlers** that return only public file, task, project and activity fields; register exact permissions/effects.
- [ ] **Step 5: Implement partial Pydantic validation** by constructing cached optional versions of primitive models while preserving field metadata and `extra="forbid"`; retain complete validation in `execute`.
- [ ] **Step 6: Run** `python -m pytest tests/test_files_tools.py -q` **and confirm all Task 1 tests pass.**

### Task 2: Tool lifecycle, statistics and invocation history

**Files:**
- Modify: `tests/test_files_tools.py`
- Modify: `app/db.py`
- Modify: `app/tools.py`
- Modify: `app/api.py`
- Modify: `app/activity.py`

**Interfaces:**
- Produces: `db.update_tool(...) -> dict | None`
- Produces: `db.list_tool_invocations(tool_id, actor_user_id, limit) -> list[dict]`
- Produces: `db.tool_usage_for_user(actor_user_id) -> dict[str, dict]`
- Produces: `tools.update_custom_tool`, `tools.set_enabled`, `tools.duplicate_tool`, `tools.list_invocations`
- Produces: `PUT /api/herramientas/{tool_id}`, `POST /duplicar`, `GET /invocaciones`

- [ ] **Step 1: Write failing endpoint tests** for owner edit, lab admin authorization, system immutability, duplication to personal scope, own-only history and catalog statistics.
- [ ] **Step 2: Run** `python -m pytest tests/test_files_tools.py -q` **and confirm the new endpoint assertions fail.**
- [ ] **Step 3: Add DB operations** using parameterized SQL and user-scoped aggregation; history must not expose unselected columns or any invocation payload.
- [ ] **Step 4: Add service authorization and serialization** so personal ownership and lab administration are enforced in one place and usage defaults to zero.
- [ ] **Step 5: Add API models/routes and activity events** for created, updated, duplicated, enabled, disabled, denied and failed outcomes; map stable service errors to 403/404/409/422.
- [ ] **Step 6: Run** `python -m pytest tests/test_files_tools.py tests/test_activity.py -q` **and confirm all lifecycle/audit tests pass.**

### Task 3: Schema-driven Tool Workbench

**Files:**
- Create: `frontend/src/pages/ToolsPage.test.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/pages/ToolsPage.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: tool `input_schema`, `bound_arguments`, `usage` and the lifecycle/history endpoints from Task 2.
- Produces: local `SchemaField`, `ToolEditor`, `ToolRunner` and `InvocationHistory` React components.

- [ ] **Step 1: Write failing Vitest cases** that mock API responses and assert every catalog primitive appears, schema properties render as controls, only selected presets are sent, runtime values execute, and invocation history is shown.
- [ ] **Step 2: Run** `npm test -- --run frontend/src/pages/ToolsPage.test.tsx` **using the repository Vitest command and confirm the new UI assertions fail.**
- [ ] **Step 3: Extend TypeScript contracts** for JSON Schema properties, usage summaries, invocations and editor payloads without `any`.
- [ ] **Step 4: Rebuild ToolsPage** as the filtered catalog + editor/runner/history workbench; generate enum, boolean, integer, number and string inputs from schemas, falling back to JSON text.
- [ ] **Step 5: Add responsive styling** consistent with Vibi’s existing dark editorial system, visible focus states and mobile one-column layout.
- [ ] **Step 6: Run the focused Vitest file** and confirm all interaction tests pass.

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/diario.md`

**Interfaces:**
- Consumes: final primitive catalog and endpoints from Tasks 1–3.
- Produces: operator/user documentation with concrete tool and skill examples.

- [ ] **Step 1: Document** all built-in primitives, partial presets, lifecycle endpoints, permission model and an example skill that lists pending tasks and saves a daily note.
- [ ] **Step 2: Record** the design decision, migrations and verification evidence in `docs/diario.md`.
- [ ] **Step 3: Run** `python -m pytest -q` **and require a zero exit code.**
- [ ] **Step 4: Run** the full frontend Vitest suite, ESLint, `tsc --noEmit` and the production Vite build; require zero exit codes and record any non-blocking bundle warning.
- [ ] **Step 5: Inspect `git diff --check` and `git status --short`** to ensure no whitespace errors, generated caches or unrelated destructive changes were introduced.

## Self-review

- Spec coverage: all four primitives, partial presets, edit/duplicate/toggle authorization, per-user observability, schema UI, compatibility, docs and verification map to Tasks 1–4.
- Placeholder scan: no deferred implementation markers or undefined “similar” steps remain.
- Type consistency: `usage`, invocation fields and service/DB function names are defined once and consumed with matching names.

