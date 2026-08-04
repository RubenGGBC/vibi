# Skill Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir un estudio de skills versionadas, validables, exportables y ejecutables sobre las herramientas seguras de Morgana.

**Architecture:** `app/skills.py` será el límite de dominio: normaliza manifiestos, aplica autorización, compila `SKILL.md` y ejecuta herramientas mediante `app/tools.py`. SQLite conservará el estado actual y snapshots inmutables; FastAPI y el core de mensajes expondrán el caso de uso, mientras React ofrecerá un workbench de creación y prueba.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, React 19, TypeScript, TanStack Query, Vitest y Testing Library.

## Global Constraints

- No añadir dependencias ni cargar Python, shell, SQL o módulos desde SQLite.
- Una skill admite cero a cuatro herramientas y una herramienta se ejecuta como máximo una vez por petición.
- Los comandos de chat usan exclusivamente `/skill <slug> <petición>`; no hay activación implícita por clasificación.
- Skills personales y revisiones quedan aisladas por usuario; publicar o editar alcance `lab` exige `is_admin`.
- Las skills `lab` no pueden referenciar tools personales.
- Los resultados de herramientas son datos no confiables y se recortan antes de enviarlos al modelo.
- Conservar todos los cambios no relacionados ya presentes en el worktree.
- El directorio `.git` del entorno es de solo lectura; registrar los límites de commit previstos sin forzar escrituras destructivas.

## File map

- Create `app/skills.py`: dominio, validación, autorización, exportación, comandos y runner.
- Modify `app/db.py`: tablas, índices y operaciones transaccionales de skills/versiones.
- Modify `app/tools.py`: resolución pública y segura de una tool para composición.
- Modify `app/api.py`: modelos HTTP y endpoints `/api/skills`.
- Modify `app/core/messages.py`: invocación explícita compartida por PWA, Cara y Telegram.
- Modify `app/activity.py`: proyección allowlisted de eventos de skills.
- Create `tests/test_skills.py`: pruebas de dominio, API, runner y comando.
- Create `frontend/src/pages/SkillsPage.tsx`: catálogo, editor, exportación y playground.
- Create `frontend/src/pages/SkillsPage.test.tsx`: flujo principal y fallos recuperables.
- Modify `frontend/src/types.ts`: contratos de skill y ejecución.
- Modify `frontend/src/App.tsx` and `frontend/src/components/AppShell.tsx`: ruta y navegación.
- Modify `frontend/src/styles.css`: identidad visual y responsive del workbench.
- Modify `README.md` and `docs/diario.md`: uso, seguridad y registro de entrega.

## Frontend direction

**Subject and job:** un propietario técnico compone procedimientos confiables;
la página debe llevar una idea desde borrador hasta skill activa y comprobada.

**Tokens:** Obsidian `#0b0911` para fondo, Glass `#171321` para superficies,
Moon `#f0edf8` para lectura, Amethyst `#9d7bff` para edición, Sage `#79c7a5`
para preparación y Ember `#e0a56b` para avisos. Se conservan Newsreader para
títulos, Manrope para texto y JetBrains Mono para comandos, versiones y schemas.

**Layout:** el editor se comporta como una mesa de trabajo, no como un dashboard.

```text
┌ título + explicación                         [Nueva skill] ┐
├──────────── catálogo ───────────┬──── editor / playground ─┤
│ Activa · v3 · personal          │ ○ Identidad              │
│ /skill resumir-expediente       │ │ Instrucciones           │
│ tools: files.read               │ │ Capacidades              │
│ [Probar] [Editar] [Exportar]     │ ● Ejemplos + sello listo  │
└─────────────────────────────────┴───────────────────────────┘
```

**Signature:** una “costura” vertical enlaza las cuatro partes reales del
manifiesto y termina en un sello de preparación. Es información estructural:
los nodos incompletos explican qué impide activar, no son decoración.

**Design critique:** el primer impulso era una fila de métricas y cards de
dashboard, patrón demasiado genérico y ya usado en Actividad. Se elimina. El
catálogo denso y la mesa de edición comunican que se está construyendo un
artefacto; la única apuesta visual es la costura del manifiesto. Movimiento
limitado a transiciones de estado y desactivado con `prefers-reduced-motion`.

---

### Task 1: Persistencia y validación del manifiesto

**Files:**
- Create: `app/skills.py`
- Modify: `app/db.py`
- Modify: `app/tools.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Produces: `skills.create_skill(user, payload) -> dict`, `skills.update_skill(user, skill_id, payload) -> dict`, `skills.set_enabled(user, skill_id, enabled) -> dict`, `skills.duplicate_skill(user, skill_id) -> dict`, `skills.list_visible(user) -> list[dict]`, `skills.list_versions(user, skill_id) -> list[dict]`, `tools.resolve_catalog_tool(tool_id, user_id) -> dict | None`.
- Produces serialized fields: `id`, `slug`, `name`, `description`, `instructions`, `examples`, `tool_ids`, `tools`, `scope`, `enabled`, `version`, `quality`, `created_at`, `updated_at`.

- [ ] **Step 1: Write failing storage and domain tests**

```python
def test_create_update_preserves_immutable_versions(self):
    created = skills.create_skill(self.user, self.valid_payload())
    updated = skills.update_skill(
        self.user, created["id"], {**self.valid_payload(), "name": "Expediente breve"}
    )
    self.assertEqual(updated["version"], 2)
    self.assertEqual(
        [item["version"] for item in skills.list_versions(self.user, created["id"])],
        [2, 1],
    )

def test_other_user_cannot_see_personal_skill(self):
    created = skills.create_skill(self.user, self.valid_payload())
    self.assertNotIn(created["id"], {s["id"] for s in skills.list_visible(self.other)})
    with self.assertRaises(skills.SkillNotFound):
        skills.list_versions(self.other, created["id"])
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python -m pytest tests/test_skills.py -q`

Expected: collection fails because `app.skills` does not exist.

- [ ] **Step 3: Add idempotent SQLite schema and transactions**

Add `skills` with JSON text columns and partial unique indexes, plus
`skill_versions(skill_id, version, snapshot, created_at)`. Implement DB helpers
that insert the current row and version snapshot in one `_conn()` transaction,
update with `version = version + 1`, query visible rows and fetch revisions in
descending version order.

- [ ] **Step 4: Implement normalization, authorization and quality report**

Use these domain types and limits:

```python
MAX_TOOLS = 4
MAX_INSTRUCTIONS = 8_000

class SkillError(Exception): ...
class SkillNotFound(SkillError): ...
class SkillForbidden(SkillError): ...
class SkillConflict(SkillError): ...
class InvalidSkill(SkillError): ...

def validate_manifest(user: dict, manifest: dict) -> tuple[dict, dict]:
    """Return normalized manifest and {ready, score, issues}."""
```

Normalize a lowercase ASCII slug with hyphens, trim/deduplicate examples and
tool ids, reject inaccessible or disabled tools, and require admin for `lab`.
Activation requires name length at least 3, description at least 20,
instructions at least 40 and one example. Drafts expose these as errors in the
quality report but may be saved; structural tool errors always raise.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_skills.py -q`

Expected: persistence, isolation, slug conflicts, lab restrictions, quality,
activation, duplication and version ordering pass.

- [ ] **Step 6: Record intended commit boundary**

Intended commit: `feat: add versioned skill manifests`

### Task 2: Exportación, runner restringido e invocación por chat

**Files:**
- Modify: `app/skills.py`
- Modify: `app/core/messages.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: Task 1 serialized skills and `tools.resolve_catalog_tool`.
- Produces: `skills.export_skill(user, skill_id) -> dict[str, str]`, `skills.run_skill(user, skill_id, request, allow_draft=False) -> dict`, `skills.parse_command(text) -> tuple[str, str] | None`, `skills.get_active_by_slug(user, slug) -> dict | None`.
- `run_skill` returns `response`, `skill_id`, `skill_version`, `tool_runs` and `artifacts`.

- [ ] **Step 1: Write failing export and runner tests**

```python
async def test_runner_only_executes_declared_tools(self):
    skill = skills.create_skill(self.user, self.valid_payload(tool_ids=["files.search"]))
    skills.set_enabled(self.user, skill["id"], True)
    with patch("app.skills.ai_providers.complete_text", AsyncMock(side_effect=[
        '{"query":"beca","limit":20}', "He encontrado el expediente."
    ])), patch("app.skills.tools.execute", AsyncMock(return_value={
        "tool_id": "files.search", "result": {"files": []}
    })) as execute:
        result = await skills.run_skill(self.user, skill["id"], "Busca mi beca")
    execute.assert_awaited_once_with("files.search", self.user, {"query": "beca", "limit": 20})
    self.assertEqual(result["response"], "He encontrado el expediente.")

def test_export_compiles_portable_skill_md(self):
    exported = skills.export_skill(self.user, self.skill_id)
    self.assertEqual(exported["filename"], "resumir-expediente.SKILL.md")
    self.assertIn("---\nname: resumir-expediente", exported["content"])
    self.assertIn("## Herramientas disponibles", exported["content"])
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/test_skills.py -q`

Expected: missing `export_skill`, `run_skill` and command handling.

- [ ] **Step 3: Implement deterministic export and bounded runner**

Compile YAML values with JSON string quoting. For each selected tool, request a
JSON object using only its `input_schema`, parse fenced or plain JSON, then call
`tools.execute`. Serialize tool results with `ensure_ascii=False`, cap the total
context at 24,000 characters, label it untrusted, and perform one final tools-lane
completion using the skill instructions. Gather unique files from `result.files`.

- [ ] **Step 4: Add explicit shared-channel invocation**

Before `router.clasificar`, parse this anchored expression:

```python
r"^/skill\s+([a-z0-9][a-z0-9-]{0,63})(?:\s+(.+))?$"
```

Resolve only active visible skills. Persist the user and assistant conversation
messages, broadcast both using `events.mensaje_chat`, log `skill_invoked`, and
return `ResultadoMensaje("herramienta", respuesta=..., artifacts=...)`. Missing
request produces a concise usage response without calling a model.

- [ ] **Step 5: Run focused and core regression tests**

Run: `python -m pytest tests/test_skills.py tests/test_messages.py -q`

Expected: explicit command, inactive/missing behavior, persistence, export,
prompt boundary and allowlisted execution pass.

- [ ] **Step 6: Record intended commit boundary**

Intended commit: `feat: run and export constrained skills`

### Task 3: API autenticada y bitácora

**Files:**
- Modify: `app/api.py`
- Modify: `app/activity.py`
- Test: `tests/test_skills.py`
- Test: `tests/test_activity.py`

**Interfaces:**
- Consumes all Task 1 and Task 2 service functions.
- Produces the eight `/api/skills` endpoints from the design, all under
  `Depends(auth.current_user)`.

- [ ] **Step 1: Write failing API contract tests**

```python
def test_skill_lifecycle_through_api(self):
    created = self.client.post("/api/skills", headers=self.headers, json=self.payload())
    self.assertEqual(created.status_code, 201)
    skill_id = created.json()["id"]
    activated = self.client.post(
        f"/api/skills/{skill_id}/estado",
        headers=self.headers,
        json={"enabled": True},
    )
    self.assertTrue(activated.json()["enabled"])
    self.assertEqual(
        self.client.get(f"/api/skills/{skill_id}/exportar", headers=self.headers).status_code,
        200,
    )
```

Also assert 404 across users, 409 for duplicate slug/not-ready activation, 403
for non-admin lab publication, and 422 for more than four tool ids.

- [ ] **Step 2: Run API tests and confirm RED**

Run: `python -m pytest tests/test_skills.py -q`

Expected: `/api/skills` returns 404.

- [ ] **Step 3: Implement request models, endpoint mapping and events**

Use a shared `GuardarSkillBody` with field maxima from the domain, map
`SkillNotFound` to 404, `SkillForbidden` to 403, `SkillConflict` to 409 and
`InvalidSkill` to 422 except activation-quality conflicts, which return 409.
Log `skill_created`, `skill_updated`, `skill_enabled`, `skill_disabled`,
`skill_duplicated` and `skill_run` without instructions or user requests.

- [ ] **Step 4: Extend safe activity projection**

Add the skill event types to category `herramientas`, use allowlisted titles and
derive detail only from `scope`, `version` and safe skill name lookup. Never
expose instructions, prompt, tool arguments or model output.

- [ ] **Step 5: Run backend suite**

Run: `python -m pytest -q`

Expected: all existing and new backend tests pass.

- [ ] **Step 6: Record intended commit boundary**

Intended commit: `feat: expose skill studio api`

### Task 4: Workbench React de creación y prueba

**Files:**
- Create: `frontend/src/pages/SkillsPage.tsx`
- Create: `frontend/src/pages/SkillsPage.test.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes API contracts from Task 3 and existing `Tool` type.
- Produces route `/skills`, React Query key `["skills"]`, and no new dependency.

- [ ] **Step 1: Write failing UI flow test**

```tsx
it("crea, activa, prueba y exporta una skill", async () => {
  renderSkillsPageWithMockApi();
  await userEvent.click(await screen.findByRole("button", { name: "Nueva skill" }));
  await userEvent.type(screen.getByLabelText("Nombre"), "Resumir expediente");
  await userEvent.type(screen.getByLabelText("Descripción"), validDescription);
  await userEvent.type(screen.getByLabelText("Instrucciones"), validInstructions);
  await userEvent.type(screen.getByLabelText("Ejemplos"), "Resume mi matrícula");
  await userEvent.click(screen.getByRole("checkbox", { name: /Leer uno de mis archivos/ }));
  await userEvent.click(screen.getByRole("button", { name: "Guardar borrador" }));
  expect(await screen.findByText("/skill resumir-expediente")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Activar" }));
  expect(await screen.findByText("Activa")).toBeInTheDocument();
});
```

Add a second test for a failed fetch and a server quality error that remains
visible beside the editor.

- [ ] **Step 2: Run the page test and confirm RED**

Run: `node_modules/.bin/vitest.cmd --run --config vitest.config.ts src/pages/SkillsPage.test.tsx`

Expected: module `SkillsPage` missing.

- [ ] **Step 3: Implement types, queries and mutation flows**

Define `SkillIssue`, `SkillQuality`, `SkillSummary`, `SkillRun` and
`SkillsResponse`. Build a controlled editor with examples split by newline,
tool checkboxes, create/update mutation, status mutation, duplicate, export
preview and playground mutation. Invalidate `["skills"]` after every write.

- [ ] **Step 4: Implement the manifest workbench design**

Use a two-pane catalog/editor above 940px and a single-column flow below it.
Render the four meaningful editor stages on one vertical binding line, a quality
seal with actionable issues, visible permission/effect chips and `aria-live`
status. Keep all buttons keyboard reachable; provide text in addition to color;
respect `prefers-reduced-motion: reduce`.

- [ ] **Step 5: Wire route and navigation**

Add `/skills` before `/herramientas` and a `Sparkles` navigation item labeled
`Skills`; retain Tools as the lower-level capability catalog.

- [ ] **Step 6: Run frontend tests and static checks**

Run:

```powershell
& '.\node_modules\.bin\vitest.cmd' --run --config vitest.config.ts
& '.\node_modules\.bin\eslint.cmd' .
& '.\node_modules\.bin\tsc.cmd' --noEmit -p tsconfig.app.json
& '.\node_modules\.bin\tsc.cmd' --noEmit -p tsconfig.node.json
```

Expected: all commands exit zero.

- [ ] **Step 7: Record intended commit boundary**

Intended commit: `feat: add skill studio workbench`

### Task 5: Documentación y verificación final

**Files:**
- Modify: `README.md`
- Modify: `docs/diario.md`

**Interfaces:**
- Documents the final contracts and operational limits; introduces no runtime API.

- [ ] **Step 1: Document the user workflow and security boundary**

Explain create → validate → activate → `/skill` → inspect activity, the eight
endpoints, portable export, immutable versions, personal/lab authorization,
maximum four tools and lack of arbitrary code or implicit activation.

- [ ] **Step 2: Run final verification from fresh command invocations**

```powershell
python -m pytest -q
& '.\node_modules\.bin\vitest.cmd' --run --config vitest.config.ts
& '.\node_modules\.bin\eslint.cmd' .
& '.\node_modules\.bin\tsc.cmd' --noEmit -p tsconfig.app.json
& '.\node_modules\.bin\tsc.cmd' --noEmit -p tsconfig.node.json
& '.\node_modules\.bin\vite.cmd' build
```

Expected: every command exits zero; the Vite build emits the PWA assets.

- [ ] **Step 3: Review security and changed files**

Run `git diff --check`, `git diff --stat`, `git status --short` and inspect the
complete diff for user isolation, secret leakage, prompt boundaries, missing
activity allowlists and accidental changes to the prior Activity feature.

- [ ] **Step 4: Record intended commit boundary**

Intended commit: `docs: explain skill studio workflow`
