# Antigravity Turn Liveness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evitar fallbacks falsos mientras Antigravity ejecuta herramientas y reenviar una sola vez los turnos que la CLI no registra.

**Architecture:** `agy_client.py` convierte cualquier actualización de trayectoria en un latido y expone un contador local de pasos `USER_INPUT`. `antigravity_chat.py` usa esos latidos para elegir el plazo de silencio y confirma el contador antes/después del tecleo, con un único reintento.

**Tech Stack:** Python 3.12, asyncio, Connect-JSON, unittest/pytest y Docker Compose.

## Global Constraints

- Silencio normal: 25 segundos.
- Silencio con herramienta activa: 60 segundos.
- Límite absoluto del turno: 180 segundos.
- Máximo de envíos por PTY: 2.
- Los latidos no se locutan ni alteran el texto acumulado.
- No modificar el frontend, el fallback ni la persistencia de mensajes.
- El árbol contiene cambios concurrentes del usuario; no confirmar archivos de producción ni tests.

---

### Task 1: Exponer latidos y acuse en el cliente

**Files:**
- Modify: `app/executors/agy_client.py:16-250`
- Test: `tests/test_agy_client.py`

**Interfaces:**
- Consumes: `stepsUpdate.steps` y `GetCascadeTrajectorySteps` del language server.
- Produces: `Update.activity: bool`, `Update.tools_running: bool` y `AgyClient.user_input_count(cascade_id: str) -> int`.

- [ ] **Step 1: Escribir pruebas RED para latidos y contador**

Añadir pruebas que exijan que una actualización sin texto salga del iterador y
que el contador incluya solo entradas del usuario:

```python
def test_una_herramienta_sin_texto_sale_como_latido(self):
    servidor = self._servidor({
        "StreamAgentStateUpdates": _sobre(_paso_herramienta(
            "CORTEX_STEP_TYPE_SEARCH_WEB", "CORTEX_STEP_STATUS_RUNNING"
        ))
    })
    recibidos = list(agy_client.AgyClient(servidor.port).stream_updates("abc-123"))
    self.assertEqual(len(recibidos), 1)
    self.assertTrue(recibidos[0].activity)
    self.assertTrue(recibidos[0].tools_running)
    self.assertIsNone(recibidos[0].text)

def test_cuenta_solo_las_entradas_del_usuario(self):
    pasos = {"steps": [
        {"type": "CORTEX_STEP_TYPE_USER_INPUT"},
        {"type": "CORTEX_STEP_TYPE_PLANNER_RESPONSE"},
        {"type": "CORTEX_STEP_TYPE_USER_INPUT"},
    ]}
    servidor = self._servidor({"GetCascadeTrajectorySteps": json.dumps(pasos).encode()})
    self.assertEqual(agy_client.AgyClient(servidor.port).user_input_count("abc-123"), 2)
```

- [ ] **Step 2: Ejecutar las pruebas y comprobar el fallo correcto**

Run: `python -m pytest -q tests/test_agy_client.py -k "latido or cuenta_solo"`

Expected: FAIL porque el iterador devuelve `[]` y `user_input_count` no existe.

- [ ] **Step 3: Implementar la ampliación mínima del cliente**

Ampliar `Update` y marcar actividad en `read_update`:

```python
@dataclass(frozen=True)
class Update:
    text: str | None = None
    done: bool = False
    herramientas: tuple[tuple[str, str], ...] = ()
    activity: bool = False
    tools_running: bool = False
```

En `_iter_updates`, usar `dataclasses.replace` para adjuntar el estado agregado,
entregar latidos y conservar el filtrado de metadatos:

```python
estado_herramientas.update(update.herramientas)
update = replace(
    update,
    tools_running=_hay_herramientas_a_medias(estado_herramientas),
)
if update.text is None:
    if update.activity:
        yield update
    continue
```

Añadir el contador:

```python
def user_input_count(self, cascade_id: str) -> int:
    data = self._post(
        "GetCascadeTrajectorySteps",
        {"cascadeId": cascade_id, "conversationId": cascade_id},
    )
    return sum(
        step.get("type") == "CORTEX_STEP_TYPE_USER_INPUT"
        for step in data.get("steps") or []
    )
```

- [ ] **Step 4: Verificar el cliente completo**

Run: `python -m pytest -q tests/test_agy_client.py`

Expected: todas las pruebas de `agy_client` pasan.

### Task 2: Confirmar el tecleo y aplicar timeouts por estado

**Files:**
- Modify: `app/executors/antigravity_chat.py:46-273`
- Test: `tests/test_antigravity_chat.py`

**Interfaces:**
- Consumes: `Update.activity`, `Update.tools_running` y `AgyClient.user_input_count`.
- Produces: `_send_confirmed(session, enviar) -> None` y `_silence_timeout(tools_running: bool) -> float`.

- [ ] **Step 1: Escribir pruebas RED para texto, plazos y reintento**

Cubrir cuatro comportamientos:

```python
def test_el_plazo_es_mayor_mientras_hay_herramienta(self):
    self.assertEqual(antigravity_chat._silence_timeout(False), 25.0)
    self.assertEqual(antigravity_chat._silence_timeout(True), 60.0)

async def test_un_latido_no_borra_la_respuesta(self):
    cliente = _ClienteFalso([
        agy_client.Update(text="Buscando", tools_running=True),
        agy_client.Update(activity=True, tools_running=True),
        agy_client.Update(text="Resultado final", done=True),
    ])
    respuesta = await antigravity_chat._consume_turn(
        self._sesion(cliente), {"id": "u"}, "c", turn_id=None
    )
    self.assertEqual(respuesta, "Resultado final")

async def test_reintenta_una_vez_si_el_primer_tecleo_no_se_registra(self):
    cliente = _ClienteConContadores([0, 0, 1])
    enviados = []
    with patch.object(antigravity_chat, "INPUT_ACK_TIMEOUT", 0):
        await antigravity_chat._send_confirmed(
            self._sesion(cliente), lambda: _registrar(enviados)
        )
    self.assertEqual(len(enviados), 2)

async def test_dos_tecleos_sin_acuse_fallan(self):
    cliente = _ClienteConContadores([0, 0, 0])
    with patch.object(antigravity_chat, "INPUT_ACK_TIMEOUT", 0):
        with self.assertRaises(AgyUnavailable):
            await antigravity_chat._send_confirmed(
                self._sesion(cliente), AsyncMock()
            )
```

- [ ] **Step 2: Ejecutar las pruebas y comprobar el fallo correcto**

Run: `python -m pytest -q tests/test_antigravity_chat.py -k "latido or plazo or reintenta or sin_acuse"`

Expected: FAIL porque los helpers y campos aún no existen o porque el latido
vacía `TurnText`.

- [ ] **Step 3: Implementar confirmación y plazos**

Añadir constantes y helper puro:

```python
TOOL_SILENCE_TIMEOUT = 60.0
INPUT_ACK_TIMEOUT = 3.0
INPUT_ACK_POLL = 0.1
INPUT_SEND_ATTEMPTS = 2

def _silence_timeout(tools_running: bool) -> float:
    return TOOL_SILENCE_TIMEOUT if tools_running else TURN_SILENCE_TIMEOUT
```

Implementar `_send_confirmed` tomando el contador antes del primer envío,
consultándolo hasta que aumente y repitiendo como máximo una vez. Las consultas
se ejecutan con `asyncio.to_thread` y los errores de `AgyClient` no se ocultan.

En `_consume_turn`, abrir el stream antes del acuse, usar `_send_confirmed` y
actualizar `tools_running` con cada item. Procesar texto solo así:

```python
tools_running = item.tools_running
if item.text is not None:
    nuevo = turno.advance(item.text)
    if nuevo and turn_id:
        await events.fragmento_chat(
            user["id"], conversation_id, turn_id, nuevo, boundary=True
        )
```

La espera usa `min(restante, _silence_timeout(tools_running))`; el deadline
absoluto no cambia.

- [ ] **Step 4: Verificar el motor completo**

Run: `python -m pytest -q tests/test_antigravity_chat.py`

Expected: todas las pruebas del motor pasan.

### Task 3: Regresión conjunta y despliegue

**Files:**
- Verify: `app/executors/agy_client.py`
- Verify: `app/executors/antigravity_chat.py`
- Verify: `docker-compose.yml`

**Interfaces:**
- Consumes: los cambios verdes de Tasks 1 y 2.
- Produces: el contenedor `vibi` ejecutando la lógica verificada.

- [ ] **Step 1: Ejecutar la regresión específica conjunta**

Run: `python -m pytest -q tests/test_agy_client.py tests/test_antigravity_chat.py`

Expected: todas las pruebas pasan.

- [ ] **Step 2: Reconstruir el servicio**

Run: `docker compose up -d --build vibi`

Expected: imagen construida y contenedor recreado con código de salida cero.

- [ ] **Step 3: Comprobar el runtime y el arranque**

Run: `docker compose exec -T vibi python -c "from app.executors import agy_client, antigravity_chat; assert hasattr(agy_client.AgyClient, 'user_input_count'); assert antigravity_chat.TOOL_SILENCE_TIMEOUT == 60.0"`

Run: `docker compose ps` y `docker compose logs --tail=120 vibi`.

Expected: el runtime contiene ambas defensas, `vibi` está `Up` y Uvicorn
completa el arranque sin una excepción nueva.

