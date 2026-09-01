# Enseñar en vez de hacer — Plan de implementación

**Objetivo:** que Vibi pueda señalar en la pantalla del usuario —una foto suya
con recuadros numerados sobre los elementos de los que habla— en vez de tomarle
el ratón.

**Arquitectura:** una capacidad más del nodo (`ui.guide`), una primitiva más del
catálogo (`devices.ui_guide`) y un almacén efímero en el servidor
(`app/guias.py`) con URL propia. Las marcas viajan como geometría y las dibuja
la PWA con un SVG encima de la foto. La guía llega al usuario por el canal de
eventos, no colgada de la respuesta del turno.

**Stack:** Python 3.11, FastAPI, React 19 + TypeScript, unittest/pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-01-ensenar-en-vez-de-hacer-design.md`

## Restricciones

- Señalar no toca nada: ni ratón, ni teclado, ni foco de ventana.
- Ninguna dependencia nueva en el nodo (Pillow solo está declarada en Windows).
- La imagen no entra en el contexto del modelo ni se guarda en disco.
- El prompt de Antigravity tiene un tope de tamaño (13.000 caracteres) y hay un
  test que lo vigila: lo que se añada allí sale de quitar algo dicho dos veces.

---

### Tarea 1: La aritmética de señalar, en el nodo

**Archivos:**
- Crear: `agent/vibi_node/guia.py`
- Modificar: `agent/vibi_node/screen.py` (publicar `pantallas()`)
- Crear: `tests/test_guia.py`

**Interfaces:**
- Produce: `guia.senalar(objetivos, ventana) -> {jpeg, marcas, detalle}`.
- Produce: `guia.proyectar(rect, detalle) -> {x, y, ancho, alto, recortada} | None`.
- Consume: `ui._mirar`, `ui_tree.por_ref`, `ui_tree.buscar`, `screen.capturar`.

- [x] Pruebas de la proyección con dos monitores y origen negativo, del
      recorte, de la elección de pantalla y de la resolución de objetivos.
- [x] `senalar` resuelve por `ref` (comprobando contra la lectura anterior) o
      por descripción, y devuelve error entendible en ambiguo, no encontrado y
      ref caducado.
- [x] Elegir el monitor donde cae el objetivo y proyectar sobre esa foto.
- [x] Verificar que el backend no recibe ninguna acción durante una guía.

### Tarea 2: La capacidad del nodo

**Archivos:**
- Modificar: `agent/vibi_node/capabilities.py`

**Interfaces:**
- Produce: capacidad `ui.guide` (condicional: solo donde hay árbol).
- Produce: `_subir_imagen`, común con `screen.capture`.

- [x] Extraer la subida HTTP de la captura a una función compartida.
- [x] `_ui_guide` sube el JPEG y devuelve solo el recibo con las marcas.
- [x] Rechazar la trastienda: allí no hay nadie mirando.

### Tarea 3: El almacén efímero y su URL

**Archivos:**
- Crear: `app/guias.py`
- Modificar: `app/main.py`
- Crear: `tests/test_guias.py`

**Interfaces:**
- Produce: `guias.publicar(user_id, imagen)`, `guias.obtener(id, user_id)`.
- Produce: `GET /api/guias/{id}/imagen` autenticado y con dueño.

- [x] Caducidad de diez minutos, tope de guías en memoria y limpieza perezosa.
- [x] 401 sin token, 403 con el de otra persona, 404 caducada, `no-store`.

### Tarea 4: La herramienta

**Archivos:**
- Modificar: `app/tools.py`, `app/nodes.py`, `app/events.py`

**Interfaces:**
- Produce: primitiva `devices.ui_guide` con permisos `devices:read:self`.
- Produce: evento `{"tipo": "guia", "guia": {...}}`.

- [x] `ui.guide` en `CAPACIDADES_LECTURA` y en `CAPACIDADES_CON_CONTENIDO_AJENO`.
- [x] La imagen va al usuario por el evento; al modelo, solo qué número quedó
      sobre qué.
- [x] La orden no se encola si el nodo está apagado.

### Tarea 5: Que los dos motores sepan que existe

**Archivos:**
- Modificar: `app/executors/claude_chat.py`, `app/executors/antigravity_chat.py`

- [x] Párrafo en el prompt de Claude: cuándo enseñar y cuándo hacer.
- [x] Fila en la tabla de Antigravity y firma en las herramientas de cabecera.
- [x] Recortar la duplicación necesaria para no rebasar el tope del prompt: el
      mecanismo de las coordenadas estaba escrito aquí y, palabra por palabra,
      en la descripción de `devices_click`, que `agy` ya recibe.

### Tarea 6: Enseñarla en la PWA

**Archivos:**
- Crear: `frontend/src/components/GuiaCard.tsx`, `GuiaCard.test.tsx`
- Modificar: `frontend/src/types.ts`, `frontend/src/styles/vibi-ui.css`,
  `frontend/src/components/ChatPanel.tsx`, `frontend/src/pages/ChatPage.tsx`

- [x] Tipos `Guia` y `GuiaMarca`, y el evento en `ServerEvent`.
- [x] Componente con la foto, el SVG de marcas en coordenadas de la imagen y la
      leyenda numerada; caducada se explica en vez de fallar.
- [x] Las dos superficies de chat escuchan el evento y la añaden como línea
      efímera.
