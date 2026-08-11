# Vibi Rebranding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the complete active product identity from Morgana to Vibi without changing behavior or losing existing configuration and data.

**Architecture:** Apply one canonical `Vibi`/`vibi` namespace across the backend, node agent, web UI, desktop companion, wake listener, deployment files, and documentation. Keep narrowly scoped legacy readers for persisted settings, environment variables, database paths, and old launch commands; all newly written state and all user-facing output use Vibi.

**Tech Stack:** Python 3.11, FastAPI, Pydantic Settings, SQLite, React 19, TypeScript, Vitest, Tauri 2, Rust, Vosk, Docker Compose.

## Global Constraints

- Product behavior, visual design, permissions, and capabilities must not change.
- Canonical display spelling is `Vibi`; canonical technical spelling is `vibi`; canonical environment prefix is `VIBI_`.
- The wake word is exactly `vibi`; voice-session closing phrases include `adiós Vibi` and `gracias Vibi` after normalization.
- Existing databases, desktop settings, environment variables, and node startup commands remain usable through explicit compatibility fallbacks.
- Active references to the old name are allowed only in migration code and tests that prove migration.
- Preserve unrelated uncommitted work already present in the checkout.

---

### Task 1: Backend identity and persistent-data compatibility

**Files:**
- Create: `tests/test_branding.py`
- Modify: `app/config.py`
- Modify: `app/api.py`
- Modify: `app/main.py`
- Modify: `app/channels/telegram.py`
- Modify: `app/executors/*.py`
- Modify: remaining `app/*.py`
- Modify: affected `tests/test_*.py`

**Interfaces:**
- Produces: `resolve_vibi_db_path(current: Path, legacy: Path) -> Path`, returning the new path, moving a lone legacy database when possible, and falling back to the legacy path when migration fails.
- Produces: backend identity `Vibi`, MCP server name `vibi`, and voice closing orders `{"adios vibi", "gracias vibi"}`.
- Consumes: existing `Settings`, chat engine, MCP, voice, Telegram, task, file, and activity interfaces without changing their signatures.

- [ ] **Step 1: Write failing backend branding tests**

```python
def test_default_identity_is_vibi():
    assert Settings(_env_file=None).app_name == "Vibi"

def test_vibi_db_migrates_legacy_file(tmp_path):
    legacy = tmp_path / "morgana.db"
    legacy.write_bytes(b"sqlite-data")
    current = tmp_path / "vibi.db"
    assert resolve_vibi_db_path(current, legacy) == current
    assert current.read_bytes() == b"sqlite-data"
    assert not legacy.exists()

def test_voice_session_closes_with_vibi():
    assert normalizar_orden_cierre("Gracias, Vibi") in ORDENES_CERRAR_CONVERSACION
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_branding.py tests/test_voice_session.py -q`

Expected: failures show the old default identity, missing database resolver, and old closing phrases.

- [ ] **Step 3: Implement the backend rename and safe database adoption**

Add to `app/config.py`:

```python
def resolve_vibi_db_path(current: Path, legacy: Path) -> Path:
    if current.exists() or not legacy.exists():
        return current
    current.parent.mkdir(parents=True, exist_ok=True)
    try:
        legacy.replace(current)
    except OSError:
        return legacy
    return current
```

Set `app_name` to `Vibi` and the default database through this resolver. Rename prompts, MCP server identifiers, log namespaces, errors, event payload copy, Telegram copy, and active backend symbols from the old identity to Vibi. Update assertions and fixtures without changing API contracts.

- [ ] **Step 4: Run backend tests**

Run: `python -m pytest tests/test_branding.py tests/test_api.py tests/test_voice_session.py tests/test_telegram.py tests/test_groq_chat.py tests/test_antigravity_chat.py tests/test_agy_mcp.py -q`

Expected: all selected tests pass with Vibi identity and unchanged behavior.

### Task 2: Node agent namespace and environment compatibility

**Files:**
- Rename: `agent/morgana_node/` to `agent/vibi_node/`
- Create: `agent/morgana_node/__init__.py`
- Create: `agent/morgana_node/__main__.py`
- Modify: `agent/vibi_node/*.py`
- Modify: `scripts/agente-nodo.cmd`
- Modify: `scripts/agente-nodo.vbs`
- Modify: `agent/README.md`
- Modify: node-related `tests/test_*.py`

**Interfaces:**
- Produces: canonical module command `python -m vibi_node`.
- Produces: legacy command `python -m morgana_node` as a forwarding compatibility shim only.
- Produces: `VIBI_*` environment variables with `MORGANA_*` lookup only as fallback.
- Consumes: the existing node WebSocket protocol and capability schemas unchanged.

- [ ] **Step 1: Update node tests to import the canonical package and test legacy environment fallback**

```python
from agent.vibi_node import config

def test_vibi_env_wins_over_legacy(monkeypatch):
    monkeypatch.setenv("VIBI_FS_EXCLUIR", "nuevo")
    monkeypatch.setenv("MORGANA_FS_EXCLUIR", "anterior")
    assert config.environment_value("VIBI_FS_EXCLUIR", "MORGANA_FS_EXCLUIR") == "nuevo"
```

- [ ] **Step 2: Run node tests and verify RED**

Run: `python -m pytest tests/test_node_agent.py tests/test_system_mcp.py tests/test_app_catalog.py tests/test_computer.py -q`

Expected: import or helper failures prove the canonical namespace is not implemented yet.

- [ ] **Step 3: Rename the package and add explicit fallbacks**

Move all implementation modules to `agent/vibi_node`, update imports and scripts, and add a two-file legacy shim whose `__main__` imports and calls `agent.vibi_node.__main__.main`. Add:

```python
def environment_value(current: str, legacy: str, default: str = "") -> str:
    return os.environ.get(current, os.environ.get(legacy, default))
```

Use the helper only for previously branded variables. Ensure logs, user-facing errors, MCP server names, Playwright profile defaults, and generated startup files use Vibi.

- [ ] **Step 4: Run node tests**

Run: `python -m pytest tests/test_node_agent.py tests/test_node_media.py tests/test_system_mcp.py tests/test_app_catalog.py tests/test_app_launch.py tests/test_computer.py tests/test_media_control.py -q`

Expected: all selected tests pass through the canonical Vibi package.

### Task 3: Web and companion identity with local-setting migration

**Files:**
- Rename: `frontend/src/components/MorganaFace.tsx` to `frontend/src/components/VibiFace.tsx`
- Rename: `frontend/src/components/MorganaFace.test.tsx` to `frontend/src/components/VibiFace.test.tsx`
- Rename: `frontend/public/morgana-icon.svg` to `frontend/public/vibi-icon.svg`
- Modify: `frontend/src/lib/companionApi.ts`
- Modify: `frontend/src/components/*.tsx`
- Modify: `frontend/src/pages/*.tsx`
- Modify: `frontend/src/lib/*.ts`
- Modify: `frontend/src/**/*.test.ts*`
- Modify: `frontend/index.html`
- Modify: `frontend/companion.html`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Produces: `SETTINGS_KEY = "vibi.companion.settings"` and `LEGACY_SETTINGS_KEY = "morgana.companion.settings"`.
- Produces: `VibiFace` with the same props and rendering contract as the previous face component.
- Consumes: all existing API endpoints and response types unchanged.

- [ ] **Step 1: Write the local-setting migration test and rename UI expectations**

```typescript
localStorage.setItem("morgana.companion.settings", JSON.stringify(legacy));
expect(loadCompanionSettings()).toEqual(legacy);
expect(localStorage.getItem("vibi.companion.settings")).toBe(JSON.stringify(legacy));
```

Update visible-text assertions to Vibi and component tests to import `VibiFace`.

- [ ] **Step 2: Run focused frontend tests and verify RED**

Run from `frontend`: `npm test -- --run src/lib/companionApi.test.ts src/components/CompanionApp.test.tsx src/components/VibiFace.test.tsx`

Expected: missing `VibiFace`, old storage key, and old copy cause failures.

- [ ] **Step 3: Implement the UI rename and storage migration**

`loadCompanionSettings()` first reads the Vibi key; if absent, it reads the legacy key, validates through the existing parser, writes the validated value under the Vibi key, and returns it. Saving always writes only the Vibi key. Rename display copy, accessibility labels, DOM events, icon references, package metadata, component symbols, comments, and tests while keeping UI structure and behavior unchanged.

- [ ] **Step 4: Run the complete frontend suite and builds**

Run from `frontend`: `npm test -- --run`

Run from `frontend`: `npm run build`

Run from `frontend`: `npm run build:companion`

Expected: all tests and both TypeScript/Vite builds pass.

### Task 4: Tauri desktop and Vosk wake word

**Files:**
- Modify: `frontend/src-tauri/wake/wake_listener.py`
- Modify: `frontend/src-tauri/wake/build-sidecar.ps1`
- Modify: `frontend/src-tauri/src/main.rs`
- Modify: `frontend/src-tauri/tauri.conf.json`
- Modify: `frontend/src-tauri/Cargo.toml`
- Modify: `frontend/src-tauri/Cargo.lock`
- Modify: `frontend/src-tauri/capabilities/default.json`
- Modify: `tests/test_wake_listener.py`

**Interfaces:**
- Produces: wake listener `KEYWORD = "vibi"` and Tauri events `vibi://wake`, `vibi://end-session`, and `vibi://listener-error`.
- Produces: sidecar executable name `vibi-wake.exe`.
- Consumes: legacy `MORGANA_WAKE_MODEL`, `MORGANA_PYTHON`, and `MORGANA_BASE_URL` only if the corresponding `VIBI_*` value is absent.

- [ ] **Step 1: Change wake tests to require Vibi and reject near matches**

```python
assert wake.KEYWORD == "vibi"
listener, verifier = self._listener(
    accept=True,
    final={"text": "vibi", "result": [{"word": "vibi", "conf": 0.98}]},
    confirmacion="vibi",
)
```

Keep coverage for partial results, low confidence, debounce, microphone recovery, pause, resume, and shutdown.

- [ ] **Step 2: Run wake tests and verify RED**

Run: `python -m pytest tests/test_wake_listener.py -q`

Expected: assertions fail because the listener still recognizes the old word.

- [ ] **Step 3: Implement Vibi wake and desktop namespace**

Replace the grammar and comments with Vibi, switch all emitted/listened events, sidecar paths, process names, package metadata, product title, and bundle resource names. Add a Rust helper that checks the new environment variable first and the old variable second; retain the existing Tauri identifier only if required to preserve the installed app's WebView data, documenting it as a compatibility identifier.

- [ ] **Step 4: Run wake, Rust, and companion checks**

Run: `python -m pytest tests/test_wake_listener.py -q`

Run from `frontend/src-tauri`: `cargo check`

Run from `frontend`: `npm run build:companion`

Expected: Vibi wake tests pass, Rust checks cleanly, and the companion bundle inputs resolve.

### Task 5: Deployment, documentation, filenames, and repository-wide verification

**Files:**
- Modify: `.env.example`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `IMPLEMENTACION.md`
- Modify: `docs/**/*.md`
- Rename: tracked filenames containing `morgana` to their `vibi` equivalents
- Rename: `morgana.db` to `vibi.db` without altering its bytes

**Interfaces:**
- Produces: Docker service/container `vibi`, internal root `/srv/vibi`, new example variables `VIBI_*`, and Vibi-named documentation and artifacts.
- Consumes: old environment variables only through compatibility readers implemented in earlier tasks.

- [ ] **Step 1: Rename deployment identifiers, docs, and tracked artifacts**

Update all current commands and examples to `docker compose ... vibi`, `/srv/vibi`, `VIBI_*`, `vibi_node`, and Vibi filenames. Rename archival spec/plan filenames and their textual branding so repository search results describe the current product consistently.

- [ ] **Step 2: Audit remaining old-name references**

Run: `rg -n -i --hidden --glob '!.git/**' --glob '!node_modules/**' --glob '!frontend/src-tauri/target/**' --glob '!frontend/dist*/**' 'morgana' .`

Expected: every result is an intentional legacy compatibility alias, migration fixture, or the external checkout path embedded by a tool; no visible copy, prompt, canonical identifier, or documentation uses the old identity.

- [ ] **Step 3: Run the full verification suite**

Run: `python -m pytest -q`

Run from `frontend`: `npm test -- --run`

Run from `frontend`: `npm run lint`

Run from `frontend`: `npm run build`

Run from `frontend`: `npm run build:companion`

Run from `frontend/src-tauri`: `cargo check`

Expected: every command exits zero. Any pre-existing unrelated failure is recorded with its exact command and output and is not hidden by the rebranding work.

- [ ] **Step 4: Inspect the final diff without staging unrelated work**

Run: `git status --short`

Run: `git diff --check`

Run: `git diff --stat`

Expected: no whitespace errors; all existing user changes remain present; Vibi changes are clearly identifiable.
