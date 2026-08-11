# Vibi Wake Alias Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que el wake word Vibi funcione con el vocabulario español de Vosk sin cambiar la marca ni el protocolo público.

**Architecture:** Mantener `KEYWORD = "vibi"` como valor canónico y separar la forma acústica `bibi` usada por la gramática y las dos etapas de reconocimiento. El evento emitido conserva siempre `keyword="vibi"`.

**Tech Stack:** Python 3.11, Vosk, unittest/pytest, PyInstaller, Tauri/NSIS.

## Global Constraints

- `vibi` es el único nombre público y valor emitido.
- `bibi` es un detalle interno del reconocedor.
- Aceptar `vivi` únicamente en la confirmación acústica: el modelo completo
  devuelve esa forma para la pronunciación de Vibi.
- No cambiar el protocolo JSONL ni la integración Tauri.

---

### Task 1: Reconocimiento acústico compatible

**Files:**
- Modify: `tests/test_wake_listener.py`
- Modify: `frontend/src-tauri/wake/wake_listener.py`

**Interfaces:**
- Consumes: resultados Vosk con palabras y confianza.
- Produces: evento JSONL `wake` con `keyword="vibi"`.

- [x] **Step 1: Escribir la prueba de regresión**

Añadir una prueba donde candidato y confirmación sean `bibi` y comprobar que
el evento emitido conserva `keyword="vibi"`.

Hecho en `AliasAcusticoTests`: la gramática, el caso `bibi`/`bibi` del plan y
el caso `bibi`/`viví` que describe el diseño.

- [x] **Step 2: Ejecutar la prueba y verificar RED**

Run: `python -m pytest -q tests/test_wake_listener.py`
Expected: FAIL porque `bibi` no coincide con `KEYWORD`.

Verificado contra la versión de `wake_listener.py` en HEAD: 3 failed,
14 passed. `'bibi' not found in ['vibi', '[unk]']`.

- [x] **Step 3: Implementar el cambio mínimo**

Definir una colección de formas acústicas con `vibi`, `bibi` y `vivi`, construir la
gramática sólo con `bibi` y usar la colección en `heard_keyword()` y
`confirm_keyword()`.

- [x] **Step 4: Ejecutar la suite del listener**

Run: `python -m pytest -q tests/test_wake_listener.py`
Expected: PASS.

17 passed. La suite completa del repo: 525 passed, 1 skipped.

- [x] **Step 5: Reconstruir y reinstalar**

Ejecutar `build-sidecar.ps1`, `npm run desktop:build`, el instalador NSIS
silencioso y reiniciar el Companion.

Ya instalado: `%LOCALAPPDATA%\Vibi\wake\vibi-wake.exe` (11/08/2026 18:37:40),
copia exacta del sidecar recién construido.

- [x] **Step 6: Verificar el runtime**

Comprobar que `vibi-companion`, `vibi-wake` y `vibi_node` están activos, que
el log informa `Vibi está escuchando` y que una pronunciación real despierta.

`vibi-companion` (11864), `vibi-wake` (7476 → 5468) y el agente de nodo
(python 34780, tarea «Morgana - agente de nodo» en Ready) activos; contenedor
`vibi` levantado. `wake.log` informa `Vibi está escuchando` y registra seis
despertares reales entre las 18:44 y las 23:45 del 11/08/2026.
