# Morgana PWA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar una PWA móvil-first servida por Morgana, con autenticación, API REST, eventos en vivo, integración compartida con Telegram y despliegue en un único contenedor.

**Architecture:** FastAPI expone routers protegidos y un WebSocket autenticado; la lógica compartida de mensajes, proyectos y tareas permanece en módulos de core independientes de los canales. React consume esa API mediante React Query, mantiene la caché sincronizada con el WebSocket y se compila a un `dist/` que FastAPI sirve con fallback de SPA.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, bcrypt, PyJWT, unittest, React, TypeScript, Vite, Tailwind CSS, TanStack Query, React Router, vite-plugin-pwa, Vitest.

## Global Constraints

- Todos los endpoints `/api/*`, salvo `POST /api/auth/login`, requieren `Authorization: Bearer <JWT>`.
- Los JWT expiran a los 30 días y usan `JWT_SECRET` de entorno.
- Los errores HTTP de API tienen forma `{"error": "mensaje"}`.
- La PWA es un cliente: no contiene lógica de negocio.
- Telegram y la API llaman al mismo core para procesar mensajes y resolver proyectos.
- Solo se clonan URLs HTTPS de GitHub o URLs SSH de hosts Git conocidos, y el destino debe quedar dentro del workspace del usuario.
- La UI usa React + Vite + TypeScript, Tailwind, React Query y React Router, sin Redux ni frameworks pesados de componentes.
- El tema es oscuro, mobile-first y usa un acento morado.
- La cara, voz, push web, diffs, registro multiusuario y selección de executor quedan fuera de alcance.

---

### Task 1: Persistencia de credenciales y autenticación JWT

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `app/config.py`
- Modify: `app/db.py`
- Create: `app/auth.py`
- Create: `scripts/__init__.py`
- Create: `scripts/set_password.py`
- Create: `tests/test_auth.py`
- Modify: `docs/diario.md`

**Interfaces:**
- Produces: `auth.hash_password(str) -> str`, `auth.verify_password(str, str) -> bool`, `auth.create_access_token(dict) -> str`, `auth.decode_access_token(str) -> dict`, `auth.current_user(...) -> dict`.
- Produces: `db.get_user_by_nombre(nombre)`, `db.set_password_hash(user_id, password_hash)` and an idempotent migration for `users.password_hash`.

- [ ] **Step 1: Write failing tests** for bcrypt round trips, JWT expiry/signature validation, database migration, lookup by name and setting a password hash.

```python
def test_hash_y_verificacion(self):
    encoded = auth.hash_password("secreto")
    self.assertNotEqual(encoded, "secreto")
    self.assertTrue(auth.verify_password("secreto", encoded))
    self.assertFalse(auth.verify_password("incorrecta", encoded))
```

- [ ] **Step 2: Verify RED** with `python -m unittest tests.test_auth -v`; expect import or assertion failures because `app.auth` and `password_hash` do not exist.
- [ ] **Step 3: Add dependencies and settings** for `bcrypt`, `PyJWT`, `JWT_SECRET`, `JWT_EXPIRATION_DAYS=30` and `PWA_BASE_URL`.
- [ ] **Step 4: Implement minimal auth and migration**, using bcrypt bytes, JWT `sub`/`exp`, and exact user lookup.
- [ ] **Step 5: Implement the CLI** so `python -m scripts.set_password ruben` prompts twice with `getpass`, rejects mismatch/unknown user and stores only the hash.
- [ ] **Step 6: Verify GREEN** with `python -m unittest tests.test_auth -v` and append the auth result to `docs/diario.md`.

### Task 2: Core compartido de mensajes y proyectos

**Files:**
- Create: `app/core/__init__.py`
- Create: `app/core/messages.py`
- Create: `app/projects.py`
- Modify: `app/channels/telegram.py`
- Create: `tests/test_messages.py`
- Create: `tests/test_projects.py`
- Modify: `docs/diario.md`

**Interfaces:**
- Produces: `messages.ResultadoMensaje`, `messages.procesar_mensaje(user, texto, canal)`, `messages.procesar_encargo(user, prompt, proyecto, canal)`.
- Produces: `projects.validar_url_repo(url) -> tuple[host, nombre]` and `await projects.clonar_proyecto(user_id, url) -> str`.
- Consumes: `tasks.resolver_proyecto`, `tasks.encolar_tarea`, `router.clasificar`, `groq_chat.responder`.

- [ ] **Step 1: Write failing core tests** proving quick messages return the Groq response, agentic messages enqueue a task, and ambiguous projects produce a structured resolution instead of channel-specific text.
- [ ] **Step 2: Verify RED** with `python -m unittest tests.test_messages -v`.
- [ ] **Step 3: Implement `app/core/messages.py`** with a small result dataclass and no Telegram/FastAPI imports.
- [ ] **Step 4: Refactor Telegram** to render the shared result and preserve its pending-project conversation.
- [ ] **Step 5: Write failing clone-security tests** for valid GitHub HTTPS/known SSH URLs, rejected schemes/hosts, sanitized names, collisions and destinations outside the user root.
- [ ] **Step 6: Verify RED** with `python -m unittest tests.test_projects -v`.
- [ ] **Step 7: Implement clone service** with `asyncio.create_subprocess_exec`, an argv list, a temporary sibling directory, realpath checks and cleanup on failure.
- [ ] **Step 8: Verify GREEN** with `python -m unittest tests.test_messages tests.test_projects -v` and document the shared-core refactor.

### Task 3: API REST protegida

**Files:**
- Modify: `app/db.py`
- Create: `app/serializers.py`
- Create: `app/api.py`
- Modify: `app/main.py`
- Create: `tests/test_api.py`
- Modify: `docs/diario.md`

**Interfaces:**
- Produces: `GET /api/yo`, task list/detail, approve/reject, `POST /api/mensaje`, project list and clone endpoints.
- Produces: `serializers.serializar_tarea(task) -> dict`, including `proyecto` derived from `workspace`.
- Consumes: auth dependency, shared message/project services and `tasks.aprobar_tarea` / `tasks.rechazar_tarea`.

- [ ] **Step 1: Write failing TestClient tests** for login, missing/invalid bearer credentials, `{"error": ...}` responses, user-scoped task queries, filters/limits and ownership checks.

```python
response = client.get("/api/yo")
self.assertEqual(response.status_code, 401)
self.assertEqual(response.json(), {"error": "Autenticación requerida"})
```

- [ ] **Step 2: Verify RED** with `python -m unittest tests.test_api -v`.
- [ ] **Step 3: Add DB query functions** for user-scoped newest-first task lists with optional state/project/limit.
- [ ] **Step 4: Implement API routers and schemas**; translate unresolved project selection to HTTP 409 and do not leak tasks belonging to another user.
- [ ] **Step 5: Add an API-aware HTTP exception handler** in the app factory and keep `/salud` public.
- [ ] **Step 6: Verify GREEN** with `python -m unittest tests.test_api -v` and document REST completion.

### Task 4: WebSocket y actualizaciones del orquestador

**Files:**
- Create: `app/events.py`
- Modify: `app/tasks.py`
- Modify: `app/main.py`
- Create: `tests/test_events.py`
- Modify: `docs/diario.md`

**Interfaces:**
- Produces: `events.ConnectionManager`, `events.notificar(...)`, `events.tarea_actualizada(...)`, `WS /api/eventos` autenticado en el primer frame.
- Produces: multiple task notifiers plus a task-observer callback in `tasks.py`.

- [ ] **Step 1: Write failing async tests** for per-user connection isolation, stale socket removal and complete `tarea_actualizada` payloads after each state transition.
- [ ] **Step 2: Verify RED** with `python -m unittest tests.test_events -v`.
- [ ] **Step 3: Implement connection manager and authenticated WebSocket route**, closing invalid clients with code 4401.
- [ ] **Step 4: Refactor task updates through one async helper** that persists then emits the complete serialized task; register both Telegram and WS notification callbacks without one replacing the other.
- [ ] **Step 5: Verify GREEN** with `python -m unittest tests.test_events -v` and document live events.

### Task 5: Deep-links de Telegram

**Files:**
- Modify: `app/tasks.py`
- Modify: `app/channels/telegram.py`
- Create: `tests/test_telegram.py`
- Modify: `docs/diario.md`

**Interfaces:**
- Changes: notifier signature to `(user_id, texto, task_id=None, acciones=False)`.
- Consumes: `settings.pwa_base_url`.

- [ ] **Step 1: Write failing tests** proving task notifications append exactly one `PWA_BASE_URL/tareas/<id>` link, only approval notifications add buttons, and callback actions verify task ownership.
- [ ] **Step 2: Verify RED** with `python -m unittest tests.test_telegram -v`.
- [ ] **Step 3: Implement notifier metadata and deep-link rendering** while preserving Telegram chunking and approval/rejection buttons.
- [ ] **Step 4: Verify GREEN** with `python -m unittest tests.test_telegram -v` and document the notifier change.

### Task 6: Esqueleto visual, autenticación y navegación de la PWA

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig*.json`, `frontend/vite.config.ts`, `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/styles.css`, `frontend/src/types.ts`
- Create: `frontend/src/App.tsx`, `frontend/src/lib/api.ts`, `frontend/src/lib/auth.ts`
- Create: `frontend/src/components/AppShell.tsx`, `frontend/src/components/ProtectedRoute.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/FacePage.tsx`
- Create: `frontend/src/test/setup.ts`, `frontend/src/lib/api.test.ts`
- Modify: `docs/diario.md`

**Interfaces:**
- Produces: `apiFetch<T>(path, init?)`, token storage helpers, protected routes `/`, `/tareas/:id`, `/chat`, `/proyectos`, `/cara` and public `/login`.

- [ ] **Step 1: Scaffold package metadata and write failing Vitest tests** for bearer injection and clearing/redirecting on 401.
- [ ] **Step 2: Install dependencies** with `npm install` in `frontend/` and verify RED via `npm test -- --run`.
- [ ] **Step 3: Implement API/auth helpers, providers, protected routing and responsive shell** with dark theme, purple accent, desktop rail and mobile bottom navigation.
- [ ] **Step 4: Implement login and face placeholder**, keeping the destination after successful authentication.
- [ ] **Step 5: Verify GREEN** with `npm test -- --run` and document the frontend skeleton.

### Task 7: Bandeja, detalle y sincronización WebSocket

**Files:**
- Create: `frontend/src/lib/tasks.ts`, `frontend/src/lib/useEvents.ts`
- Create: `frontend/src/components/StatusBadge.tsx`, `frontend/src/components/TaskCard.tsx`, `frontend/src/components/MarkdownContent.tsx`, `frontend/src/components/MessageComposer.tsx`
- Create: `frontend/src/pages/InboxPage.tsx`, `frontend/src/pages/TaskDetailPage.tsx`
- Create: `frontend/src/lib/tasks.test.ts`
- Modify: `docs/diario.md`

**Interfaces:**
- Produces: deterministic task ranking, relative dates, React Query keys and a reconnecting WS hook that patches both list/detail caches.

- [ ] **Step 1: Write failing tests** for `esperando_aprobacion` first, active states second, remaining tasks newest-first, and cache replacement by task id.
- [ ] **Step 2: Verify RED** with `npm test -- --run`.
- [ ] **Step 3: Implement task helpers and WS cache synchronization** using the auth token in the query string.
- [ ] **Step 4: Build Inbox** with filters, live list and focused new-task composer posting to `/api/mensaje`.
- [ ] **Step 5: Build Detail** with markdown plan/result, timestamps and prominent approve/reject controls only in the waiting state.
- [ ] **Step 6: Verify GREEN** with `npm test -- --run` and document the core PWA screens.

### Task 8: Chat y proyectos

**Files:**
- Create: `frontend/src/pages/ChatPage.tsx`
- Create: `frontend/src/pages/ProjectsPage.tsx`
- Create: `frontend/src/components/CloneProjectDialog.tsx`
- Create: `frontend/src/pages/ChatPage.test.tsx`
- Modify: `docs/diario.md`

**Interfaces:**
- Consumes: `POST /api/mensaje`, `GET /api/proyectos`, `POST /api/proyectos/clonar`.
- Produces: in-memory quick-chat session and agentic task cards linking to `/tareas/:id`.

- [ ] **Step 1: Write a failing interaction test** showing a rapid answer as a bubble and an agentic result as a linked task card.
- [ ] **Step 2: Verify RED** with `npm test -- --run`.
- [ ] **Step 3: Implement Chat** with bottom composer, Enter-to-send, pending/error states and current-session history only.
- [ ] **Step 4: Implement Projects** with folder list, accessible clone dialog and inline success/error feedback.
- [ ] **Step 5: Verify GREEN** with `npm test -- --run` and document both screens.

### Task 9: Instalabilidad, servidor estático y contenedor único

**Files:**
- Create: `frontend/public/morgana-icon.svg`
- Modify: `frontend/vite.config.ts`
- Create: `app/web.py`
- Modify: `app/main.py`
- Modify: `Dockerfile`
- Modify: `.dockerignore`
- Create: `tests/test_web.py`
- Modify: `README.md`, `IMPLEMENTACION.md`, `docs/diario.md`

**Interfaces:**
- Produces: manifest `Morgana`, standalone dark theme, generated service worker, static asset serving and `index.html` fallback for client-side routes.

- [ ] **Step 1: Write failing backend tests** for `/`, a real asset, SPA fallback `/tareas/id` and no fallback for missing asset filenames.
- [ ] **Step 2: Verify RED** with `python -m unittest tests.test_web -v`.
- [ ] **Step 3: Configure VitePWA and icon metadata** with auto-update registration and offline app-shell caching.
- [ ] **Step 4: Implement guarded SPA static serving** after API/WS routes.
- [ ] **Step 5: Convert Dockerfile to Node-build + Python-runtime stages** and copy `frontend/dist` into `/srv/morgana/frontend/dist`.
- [ ] **Step 6: Build and verify** with `npm test -- --run`, `npm run build`, `python -m unittest discover -s tests -v`, `python -m compileall app scripts`, and `docker compose config`.
- [ ] **Step 7: Review the original specification line by line**, update usage/deployment docs and record the complete mobile cycle in `docs/diario.md`.
