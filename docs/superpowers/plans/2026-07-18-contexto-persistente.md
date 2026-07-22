# Contexto persistente Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persistir la conversación rápida en SQLite, construir cada turno con contexto acotado por capas y permitir reiniciar el chat desde la PWA.

**Architecture:** SQLite conserva una única conversación activa por usuario y sus mensajes. `app/core/context_builder.py` ensambla el prompt sin conocer Groq; el ejecutor obtiene historial y tareas, persiste el turno y registra sus presupuestos. La API expone historial y reset autenticados, y Chat hidrata su estado desde esos endpoints.

**Tech Stack:** Python 3.11, SQLite, FastAPI, Groq SDK, React 19, TypeScript, TanStack Query.

## Global Constraints

- No crear ni ejecutar tests por petición expresa del usuario.
- `tokens_aprox` se calcula como `len(content) // 4`, sin tokenizador externo.
- Presupuestos configurables: 200 tokens para tareas vivas y 4000 para historial reciente.
- No modificar el comportamiento de la vía agéntica.
- No implementar resumen acumulativo, difusión multi-dispositivo, títulos ni búsqueda.

---

### Task 1: Persistencia SQLite

**Files:**
- Modify: `app/db.py`

**Interfaces:**
- Produces: `get_or_create_active_conversation(user_id: str) -> dict`, `reset_active_conversation(user_id: str) -> dict`, `add_conversation_message(conversation_id: str, role: str, content: str, origin: str) -> dict`, `list_active_conversation_messages(user_id: str, limit: int, before_id: int | None = None) -> list[dict]`, `list_context_messages(conversation_id: str, token_budget: int) -> list[dict]`, `list_live_tasks(user_id: str) -> list[dict]`.

- [ ] Crear tablas, restricciones e índices idempotentes, incluida la unicidad parcial de conversación activa.
- [ ] Añadir operaciones atómicas para obtener/crear y reiniciar la conversación activa.
- [ ] Añadir escritura y lectura cronológica de mensajes, con cursor opcional `before_id`.
- [ ] Añadir consulta priorizada de tareas no terminales del usuario.

### Task 2: Contexto por capas y ejecución Groq

**Files:**
- Create: `app/core/context_builder.py`
- Modify: `app/config.py`
- Modify: `app/executors/groq_chat.py`
- Modify: `app/core/messages.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: repositorio SQLite de Task 1.
- Produces: `build_turn_context(system_prompt: str, instruction_role: str, tasks: list[dict], recent_messages: list[dict], user_message: str, task_budget: int, recent_budget: int) -> BuiltContext` y `groq_chat.responder(user_id: str, nombre: str, mensaje: str, origen: str) -> str`.

- [ ] Implementar estimación, bloque compacto de tareas, recorte por mensajes completos y métricas del contexto.
- [ ] Sustituir el historial en memoria por lectura/escritura SQLite alrededor de la llamada Groq.
- [ ] Conservar el fallback de Compound reconstruyendo los roles de instrucciones correctamente.
- [ ] Registrar en debug tokens de tareas, ventana y total; mapear cada canal a `pwa`, `telegram` o `cara`.

### Task 3: API autenticada

**Files:**
- Modify: `app/api.py`

**Interfaces:**
- Produces: `GET /api/conversations/active/messages?limit=50&before_id=...` y `POST /api/conversations/reset`.

- [ ] Serializar los mensajes de la conversación activa en orden cronológico.
- [ ] Archivar la conversación activa y devolver la nueva conversación vacía.
- [ ] Mantener ambos endpoints bajo la dependencia JWT del router existente.

### Task 4: Hidratación y reset de Chat

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/pages/ChatPage.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `docs/diario.md`

**Interfaces:**
- Consumes: endpoints de Task 3.
- Produces: historial restaurado al abrir Chat y control confirmado de “Empezar de cero”.

- [ ] Cargar los últimos 50 mensajes antes de habilitar el compositor.
- [ ] Mantener la interacción optimista actual para mensajes nuevos y tarjetas agénticas.
- [ ] Añadir un botón secundario discreto, accesible y responsive que confirme antes del reset.
- [ ] Documentar la fase en el diario y revisar sintaxis Python y compilación TypeScript sin suites de tests.
