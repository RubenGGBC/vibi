# Antigravity Tool Turn Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mantener los avisos hablados de Antigravity dentro del turno mientras una herramienta sigue activa y reanudar la escucha solo tras la respuesta final.

**Architecture:** `agy_client.py` decide cuándo termina el stream usando el estado de las herramientas; `antigravity_chat.py` consume ese stream completo y usa cada `done` únicamente como frontera de locución. El frontend conserva su protocolo actual de `boundary` y termina el turno cuando responde `/api/voz`.

**Tech Stack:** Python 3.12, pytest, Connect-JSON, FastAPI y Docker Compose.

## Global Constraints

- «Ahora te lo busco» debe seguir locutándose como aviso intermedio.
- Un `done` no puede cerrar el turno si queda una herramienta en `PENDING` o `RUNNING`.
- No se añade un protocolo nuevo al frontend.
- Se conservan los timeouts y el fallback actuales.

---

### Task 1: Hacer que el cliente cierre por estado del turno

**Files:**
- Modify: `app/executors/agy_client.py:26-192`
- Test: `tests/test_agy_client.py:341`

**Interfaces:**
- Consumes: pasos de `stepsUpdate.steps` con `type` y `status`.
- Produces: `Update(text, done, herramientas)` y un iterador que solo termina al finalizar el turno completo.

- [ ] **Step 1: Verificar la regresión en la versión desplegada**

Run: `docker compose exec -T vibi python -m pytest -q tests/test_agy_client.py::SeguirElTurnoPorElStream::test_un_done_con_una_herramienta_a_medias_no_cierra_el_turno`

Expected: FAIL antes del arreglo porque la última actualización es «Ahora te lo busco.».

- [ ] **Step 2: Adjuntar los estados de herramientas a cada actualización**

En `read_update`:

```python
herramientas = tuple(
    (step.get("type") or "", step.get("status") or "")
    for step in steps
    if step.get("type") and step.get("type") not in PASOS_DE_ANDAMIAJE
)
```

- [ ] **Step 3: Cerrar solo cuando no haya herramientas activas**

En `_iter_updates`:

```python
estado_herramientas.update(update.herramientas)
if update.done and not _hay_herramientas_a_medias(estado_herramientas):
    return
```

- [ ] **Step 4: Verificar el cliente**

Run: `python -m pytest -q tests/test_agy_client.py`

Expected: todas las pruebas pasan.

### Task 2: Impedir el segundo corte en el consumidor

**Files:**
- Modify: `app/executors/antigravity_chat.py:211-245`
- Test: `tests/test_antigravity_chat.py:183`

**Interfaces:**
- Consumes: el iterador de `AgyClient.stream_updates` y sus actualizaciones acumulativas.
- Produces: eventos `fragmento_chat(..., boundary=True)` durante el turno y la respuesta final al agotarse el iterador.

- [ ] **Step 1: Verificar la regresión en la versión desplegada**

Run: `docker compose exec -T vibi python -m pytest -q tests/test_antigravity_chat.py::LocucionEnLaCara::test_un_done_intermedio_no_da_el_turno_por_acabado`

Expected: FAIL antes del arreglo porque `_consume_turn` devuelve «Ahora te lo busco.».

- [ ] **Step 2: Eliminar el corte local por `item.done`**

El bucle termina únicamente cuando el productor introduce `None`. La emisión se conserva:

```python
nuevo = turno.advance(item.text or "")
if nuevo and turn_id:
    await events.fragmento_chat(
        user["id"], conversation_id, turn_id, nuevo, boundary=True
    )
```

- [ ] **Step 3: Verificar el motor y el cliente juntos**

Run: `python -m pytest -q tests/test_agy_client.py tests/test_antigravity_chat.py`

Expected: 54 pruebas pasan.

### Task 3: Desplegar y comprobar la versión corregida

**Files:**
- Verify: `docker-compose.yml`
- Verify: `app/executors/agy_client.py`
- Verify: `app/executors/antigravity_chat.py`

**Interfaces:**
- Consumes: el contexto de build del workspace.
- Produces: el servicio `vibi` recreado con ambos lados del protocolo corregidos.

- [ ] **Step 1: Reconstruir y recrear Vibi**

Run: `docker compose up -d --build vibi`

- [ ] **Step 2: Ejecutar las regresiones dentro del contenedor nuevo**

Run: `docker compose exec -T vibi python -m pytest -q tests/test_agy_client.py tests/test_antigravity_chat.py`

Expected: 54 pruebas pasan.

- [ ] **Step 3: Comprobar el arranque del servicio**

Run: `docker compose ps` y después `docker compose logs --tail=120 vibi`.

Expected: `vibi` aparece `Up`, Uvicorn completa el arranque y no hay una excepción nueva del motor Antigravity.

