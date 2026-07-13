# Groq Web Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir búsqueda web condicional a la vía rápida de Groq mediante Groq Compound, manteniendo el historial y un fallback al modelo normal.

**Architecture:** `Settings` expondrá un interruptor y un modelo Compound separados del modelo usado por el router. `groq_chat.responder()` elegirá Compound cuando esté habilitado; Groq decidirá si buscar, y ante un error reintentará una vez con `GROQ_MODEL`. La documentación explicará la configuración, las citas y los posibles costes de búsqueda.

**Tech Stack:** Python 3, Pydantic Settings, Groq Async SDK, `unittest`, Docker/.env.

## Global Constraints

- La búsqueda se ejecuta solo a través de los sistemas Compound oficiales de Groq; no se añade un proveedor externo ni una API key nueva.
- `GROQ_WEB_SEARCH_ENABLED` estará activado por defecto.
- `GROQ_SEARCH_MODEL` tendrá como valor por defecto `groq/compound`.
- `GROQ_MODEL` seguirá siendo el modelo del router y el fallback del chat.
- El historial seguirá limitado a `MAX_TURNOS = 10` por usuario.
- No se persisten resultados web ni se modifican las tablas SQLite.

## File Map

- Modify: `app/config.py` — añadir las dos opciones de configuración de búsqueda.
- Modify: `app/executors/groq_chat.py` — seleccionar modelo, guiar el uso de búsqueda y hacer fallback.
- Create: `tests/test_groq_chat.py` — pruebas unitarias del comportamiento observable de `responder()`.
- Modify: `.env.example` — documentar las nuevas variables.
- Modify: `README.md` — explicar el uso condicional de búsqueda web en la vía rápida.
- Modify: `IMPLEMENTACION.md` — registrar configuración, fallback y límites.

### Task 1: Add failing tests for model selection, history, and fallback

**Files:**
- Create: `tests/test_groq_chat.py`

**Interfaces:**
- Consumes: `app.executors.groq_chat.responder(user_id: str, nombre: str, mensaje: str) -> str` and the global `app.config.settings`.
- Produces: executable regression coverage for the model-selection and fallback contract used by the implementation.

- [ ] **Step 1: Write the failing tests**

Create an async fake client whose `chat.completions.create(**kwargs)` records calls, returns `SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=texto))])`, or raises a configured exception. Use `unittest.IsolatedAsyncioTestCase` and clear `groq_chat._historiales` in `setUp`. Add these tests:

```python
async def test_usa_compound_cuando_la_busqueda_esta_habilitada(self):
    with patch.object(settings, "groq_web_search_enabled", True), \
         patch.object(settings, "groq_search_model", "groq/compound"), \
         patch.object(settings, "groq_model", "llama-normal"):
        resultado = await groq_chat.responder("u1", "Rubén", "¿Qué ha pasado hoy?")

    self.assertEqual(resultado, "respuesta actual")
    self.assertEqual(self.fake.calls[0]["model"], "groq/compound")

async def test_usa_modelo_normal_cuando_la_busqueda_esta_deshabilitada(self):
    with patch.object(settings, "groq_web_search_enabled", False), \
         patch.object(settings, "groq_model", "llama-normal"):
        await groq_chat.responder("u1", "Rubén", "Hola")

    self.assertEqual(self.fake.calls[0]["model"], "llama-normal")

async def test_conserva_el_historial_entre_respuestas(self):
    self.fake.responses = ["primera", "segunda"]
    with patch.object(settings, "groq_web_search_enabled", False):
        await groq_chat.responder("u1", "Rubén", "primera pregunta")
        await groq_chat.responder("u1", "Rubén", "segunda pregunta")

    mensajes = self.fake.calls[1]["messages"]
    self.assertEqual(
        [(m["role"], m["content"]) for m in mensajes[-3:]],
        [("assistant", "primera"), ("user", "segunda pregunta"), ("assistant", "segunda")],
    )

async def test_reintenta_con_modelo_normal_si_compound_falla(self):
    self.fake.responses = [RuntimeError("Compound no disponible"), "respuesta fallback"]
    with patch.object(settings, "groq_web_search_enabled", True), \
         patch.object(settings, "groq_search_model", "groq/compound"), \
         patch.object(settings, "groq_model", "llama-normal"):
        resultado = await groq_chat.responder("u1", "Rubén", "Busca el dato actual")

    self.assertEqual(resultado, "respuesta fallback")
    self.assertEqual([c["model"] for c in self.fake.calls], ["groq/compound", "llama-normal"])
```

The test fixture must patch `groq_chat._client` with the fake client so no network request is made.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -v`

Expected: FAIL with an `AttributeError` for the new settings fields, proving the tests exercise behavior that does not exist yet. Fix only test setup errors if the suite cannot collect; do not modify production code in this step.

### Task 2: Implement configurable Compound selection and fallback

**Files:**
- Modify: `app/config.py`
- Modify: `app/executors/groq_chat.py`
- Test: `tests/test_groq_chat.py`

**Interfaces:**
- Consumes: the failing tests from Task 1 and the existing `settings.groq_model`, `_historiales`, `PERSONALIDAD`, and `client()` patterns.
- Produces: `settings.groq_web_search_enabled: bool`, `settings.groq_search_model: str`, and a `responder()` that returns the final successful response while preserving one user/assistant history pair.

- [ ] **Step 1: Add the minimal settings fields**

In `Settings`, directly after `groq_model`, add:

```python
groq_web_search_enabled: bool = True
groq_search_model: str = "groq/compound"
```

- [ ] **Step 2: Run the focused tests to verify the next failure**

Run: `python -m unittest tests.test_groq_chat -v`

Expected: the tests collect and fail because `responder()` still always sends `settings.groq_model` and has no Compound fallback.

- [ ] **Step 3: Implement model selection and one fallback attempt**

In `app/executors/groq_chat.py`, extend `PERSONALIDAD` with guidance equivalent to:

```text
Cuando una respuesta dependa de información actual, noticias, precios,
versiones, normas, horarios o datos poco conocidos, usa la búsqueda web
integrada si está disponible. No busques para conversación general o hechos
estables. Si buscas, basa la respuesta en las fuentes recuperadas y conserva
las citas automáticas en el texto final.
```

Keep the existing history append before the API call, build one `messages` list, and choose the first model with:

```python
modelo = (
    settings.groq_search_model
    if settings.groq_web_search_enabled
    else settings.groq_model
)
```

Call `chat.completions.create()` with that model. If the call raises and web search was enabled, call it once more with `settings.groq_model`; if web search was disabled, re-raise the original error. Append the assistant message only after a call succeeds, then return its content. Do not append the user message again during fallback.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `python -m unittest tests.test_groq_chat -v`

Expected: all four tests PASS.

- [ ] **Step 5: Commit the implementation**

```bash
git add app/config.py app/executors/groq_chat.py tests/test_groq_chat.py
git commit -m "feat: add conditional Groq web search"
```

### Task 3: Document configuration and operational limits

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `IMPLEMENTACION.md`

**Interfaces:**
- Consumes: the public settings names from Task 2.
- Produces: user-facing setup instructions that match the runtime behavior exactly.

- [ ] **Step 1: Document the environment variables**

In `.env.example`, immediately after `GROQ_MODEL`, add:

```env
# Búsqueda web automática en preguntas que necesiten información actual
GROQ_WEB_SEARCH_ENABLED=true
# Sistema Compound de Groq; usa groq/compound-mini para una sola búsqueda rápida
GROQ_SEARCH_MODEL=groq/compound
```

- [ ] **Step 2: Update the README**

Explain under the quick-path setup that Groq Compound can perform web search automatically when the question needs current or niche information, that citations are returned in the answer, and that it can be disabled with `GROQ_WEB_SEARCH_ENABLED=false`. State that `GROQ_SEARCH_MODEL` defaults to `groq/compound` and that Compound web searches may have separate usage charges.

- [ ] **Step 3: Update the implementation record**

Add a subsection under the quick-path section of `IMPLEMENTACION.md` describing model selection, the one-attempt fallback to `GROQ_MODEL`, the absence of external search credentials, and the fact that web results are not persisted.

- [ ] **Step 4: Check documentation and diff formatting**

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 5: Commit the documentation**

```bash
git add .env.example README.md IMPLEMENTACION.md
git commit -m "docs: document Groq web search settings"
```

### Task 4: Run the full verification suite

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: all changes from Tasks 1–3.
- Produces: verified Python syntax, passing tests, and a clean project diff.

- [ ] **Step 1: Run all unit tests**

Run: `python -m unittest discover -s tests -v`

Expected: all discovered tests PASS with no errors.

- [ ] **Step 2: Compile application modules**

Run: `python -m compileall -q app tests`

Expected: exit code 0.

- [ ] **Step 3: Inspect the final project status**

Run: `git status --short`

Expected: no uncommitted changes from this feature.
