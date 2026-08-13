# Árbol de accesibilidad con acciones por lote — Diseño

**Fecha:** 2026-08-13
**Estado:** aprobado, pendiente de plan de implementación

## El problema

Vibi ya sabe usar una GUI, pero solo por píxeles: `screen.py` manda un JPEG de
1568 px y `computer.py` pincha en coordenadas de esa imagen. Funciona, y tiene
dos costes que no se arreglan afinándolo.

**El modelo tiene que adivinar dónde está todo.** Calcula el centro de un botón
a ojo sobre una imagen reescalada. Falla con elementos pequeños, con texto
denso y con cualquier cosa que se haya movido entre la captura y el clic.

**Cada acción es un turno completo del modelo.** Guardar un archivo con nombre
—abrir el menú, pulsar «Guardar como», escribir el nombre, aceptar— son cuatro
turnos, y cada uno arrastra una captura nueva para ver qué pasó. El turno del
modelo domina la latencia; el `dispatch` al nodo es ruido al lado.

Este diseño ataca las dos cosas a la vez: el modelo **lee la GUI como texto
estructurado** en vez de mirarla, y **manda varias acciones en una sola
llamada**.

## Decisiones tomadas

Cinco, todas del dueño del proyecto, y conviene no reabrirlas sin motivo nuevo:

1. **Convive con los píxeles, no los sustituye.** El árbol es el camino
   preferente; la captura y el clic por coordenadas siguen exactamente como
   están, para lo que la accesibilidad no publica: juegos, lienzos, apps
   antiguas, imágenes, PDFs rasterizados.
2. **Por el cable, JSON; delante del modelo, texto indentado.** El nodo
   devuelve siempre una estructura. Quien la convierte en texto es una función
   aparte, en un solo sitio, y por tanto la decisión es reversible sin tocar el
   nodo. Se mide en 2.733 caracteres frente a 5.235 del mismo árbol en JSON
   minificado: entre 2x y 3,5x, y el snapshot no se paga una vez sino en cada
   turno posterior que lo arrastre en contexto.
3. **Se recorta a lo visible, y lo grande se colapsa con su cuenta.** Nada que
   caiga fuera del rectángulo de la ventana entra en el árbol: lo que está
   scrolleado fuera no existe para el modelo, igual que no existe para la
   persona. Lo que aun así sea enorme se colapsa indicando cuántos elementos
   esconde, y el modelo puede pedir ese subárbol por su `ref`. **Nunca se
   omite nada en silencio.**
4. **En un lote, el objetivo se nombra por `ref` si existe y por descripción si
   no.** Es lo que permite encadenar pasos cuyo elemento aún no ha nacido
   cuando se compone el lote.
5. **macOS se escribe ahora, sin verificar.** No hay ningún Mac en la malla
   (solo dos nodos, ambos Windows), así que la capa de AX se implementa contra
   su API documentada y queda marcada como no probada, en el código y aquí.
   Windows sí se prueba de verdad.

## Arquitectura

Vive donde viven las demás capacidades del nodo: `agent/vibi_node/`, expuesto
como primitivas en `app/tools.py`. **No como servidor MCP.** El MCP
(`system_mcp.py`, `browser_mcp.py`) existe para trabajos largos que no caben en
los 45 s de `nodes.dispatch` (`app/config.py:199`); esto es lo contrario
—muchas interacciones de milisegundos— y pasar por `dispatch` da gratis el
marcado de `taint`, el registro en Actividad, los scopes y, sobre todo,
disponibilidad en **todos** los motores y no solo en los que hablan MCP.

### Por qué en Python y dentro del agente

`computer.py` invoca la CLI `usecomputer` y la deja morir en cada acción,
porque un clic no guarda estado. Un `ref` sí: es un puntero COM en Windows y un
`AXUIElement` en macOS, y ambos mueren con el proceso que los creó. El árbol
necesita un proceso vivo, y el agente ya lo es.

### Archivos nuevos

| archivo | responsabilidad | depende de la plataforma |
|---|---|---|
| `agent/vibi_node/ui_tree.py` | `Nodo`, `Snapshot`, poda, colapso, render a texto, registro de refs | no |
| `agent/vibi_node/ui_windows.py` | backend UIA: recorrer, resolver, actuar | Windows |
| `agent/vibi_node/ui_macos.py` | backend AX, misma interfaz | macOS |
| `agent/vibi_node/ui.py` | fachada: elige backend, `capturar()`, `ejecutar_lote()` | no |

El reparto sigue el de `screen.py`: **lo que no cambia entre sistemas se
escribe una vez**. Poda, colapso, render, refs y la lógica del lote son
idénticos en Windows y macOS y viven en `ui_tree.py` y `ui.py`; los backends
solo saben recorrer un árbol nativo y disparar una acción sobre un elemento.
Eso deja la mayor parte del código comprobable sin GUI.

### Interfaz que cumplen los backends

```python
class Backend(Protocol):
    def ventanas(self) -> list[Ventana]: ...
    def recorrer(self, ventana: Ventana, limites: Limites) -> NodoNativo: ...
    def sigue_vivo(self, elemento, huella: Huella) -> bool: ...
    def actuar(self, elemento, accion: str, datos: dict) -> None: ...
```

`ui.py` no importa `comtypes` ni `objc` jamás. Elige el backend por
`platform.system()` y lo importa perezosamente, como ya hace el agente con
`winrt` para el control multimedia.

## El árbol

### Modelo de datos

```python
@dataclass
class Nodo:
    ref: str | None          # e1, e2… solo si es accionable
    rol: str                 # normalizado y en español: botón, campo, celda
    nombre: str              # el nombre accesible
    valor: str | None        # el contenido, si lo tiene
    estado: frozenset[str]   # marcado, desactivado, expandido, activa
    rect: Rect               # en coordenadas de escritorio
    hijos: list["Nodo"]
    ocultos: int             # cuántos descendientes se colapsaron aquí
```

`rol` se normaliza: UIA dice `Button` y AX dice `AXButton`, y las dos cosas
salen como `botón`. El mapa de roles vive en `ui_tree.py`, uno por backend, y
es la única traducción que hace falta para que el mismo prompt funcione en las
dos plataformas.

### La poda

Se descarta, en este orden:

1. Lo que cae fuera del rectángulo de la ventana, o tiene tamaño cero, o está
   marcado como no visible por el sistema.
2. Los contenedores sin nombre, sin valor y sin acción, cuyos hijos suben al
   nivel del padre. Es la mayor parte del ruido: UIA envuelve cada cosa en tres
   `Pane` anónimos.
3. Los textos vacíos o puramente decorativos (separadores, imágenes sin nombre).

Lo que sobrevive conserva su anidamiento, porque saber qué celda va en qué
tabla y qué botón en qué diálogo es justo lo que el árbol aporta sobre una
lista plana.

### El colapso

Tras podar, si un subárbol supera `MAX_HIJOS` (200), se sustituye por una línea
que dice cuántos elementos esconde y con qué `ref` pedirlos. Se elige el
subárbol más grande primero y se repite hasta caber en `MAX_NODOS` (400).

`ui.snapshot` acepta `expandir: "e60"` para traer ese subárbol concreto en el
siguiente snapshot, con el mismo presupuesto aplicado dentro de él.

### El render

```
ventana con foco: "Presupuesto.xlsx - Excel"
otras ventanas: Chrome, Discord, Explorador

[e3] campo "Cuadro de nombres" = "B4"
     tabla "Hoja1" (filas 1-28 de 4.312)
[e6]   celda "A1" = "Concepto"
[e7]   celda "B1" = "Importe"
[e60] panel "Panel de tareas" (colapsado - 340 elementos, pide e60)
[e90] pestaña "Hoja1" (activa)

231 nodos · 1.973 omitidos (fuera de pantalla o decorativos)
```

Reglas: dos espacios por nivel; `[eN]` solo en lo accionable; `= "valor"` solo
si hay valor; los estados entre paréntesis; y **siempre** la línea final con la
cuenta de lo omitido. Esa línea es lo que impide que el modelo crea que ha
visto todo cuando no lo ha hecho.

## Refs y su caducidad

Los refs son `e1…eN` en orden de recorrido. **Cada snapshot invalida los del
anterior**: se guarda una sola generación por nodo.

El registro guarda, junto al puntero nativo, una **huella**: rol, nombre y
`RuntimeId` en Windows; `pid` más ruta de índices desde la ventana en macOS.
Antes de actuar sobre un `ref`, se revalida contra su huella. Si el elemento
murió, o sigue vivo pero cambió de rol o de nombre, el paso falla con
`ref_caducado` y el lote para.

Esto es lo que hace seguro el optimismo del batching. Un `ref` no es una
promesa de que el elemento sigue ahí: es una promesa de que **si no sigue ahí,
lo vamos a notar antes de pulsar nada**. Sin revalidación, un lote de cinco
pasos sobre una UI que se movió pulsa cinco cosas equivocadas.

Un `ref` de un snapshot anterior da un error explícito que dice que hay que
volver a mirar, no un fallo silencioso.

## El lote

### Pasos

| paso | argumentos | qué hace |
|---|---|---|
| `clic` | `ref`\|`buscar`, `boton`, `veces` | pulsa |
| `escribir` | `ref`\|`buscar`, `texto` | pone texto en un campo |
| `tecla` | `tecla`, `veces` | manda una tecla al foco actual |
| `seleccionar` | `ref`\|`buscar` | elige en lista o desplegable |
| `expandir` | `ref`\|`buscar` | despliega un nodo de árbol o un combo |
| `enfocar` | `ref`\|`buscar` | lleva el foco sin pulsar |
| `esperar` | `buscar`, `timeout_ms` | espera a que algo aparezca |
| `snapshot` | — | devuelve el árbol en ese punto |

Valores por defecto: `boton` es `left`, `veces` es 1. El `timeout_ms` de
`esperar` se recorta al presupuesto que le quede al lote, así que un paso no
puede agotarlo entero: si pide más de lo que queda, espera lo que queda y falla
con `presupuesto_agotado`.

`escribir` usa el patrón `Value` de UIA (`AXValue` en macOS) cuando el elemento
lo admite: es instantáneo, no depende del foco y no lo rompe un cambio de
ventana a mitad. Solo cuando el elemento no lo admite cae a enfocar y teclear
con `computer.teclear`. `tecla` reutiliza `computer.pulsar` sin cambios: el
envío de entrada no se duplica.

### Resolución de objetivos

Un paso apunta con `ref` o con `buscar: {rol, nombre, dentro_de}`.

Para `buscar`, sobre el árbol vivo en el momento de ejecutar ese paso:

1. Nombre exacto.
2. Si no hay, el que contiene, normalizando acentos y mayúsculas con
   `unicodedata` como ya hace `screen.py`.
3. `rol` y `dentro_de` filtran antes de comparar nombres.

**Varios candidatos es un error, no una elección.** Falla con `ambiguo`,
devuelve la lista de candidatos con sus refs y para el lote. Coger el primero
sería más fluido y es exactamente cómo se pulsa el «Eliminar» equivocado.

**Ninguno se reintenta durante 1,5 s**, sondeando cada 100 ms, porque una UI
que acaba de recibir un clic puede estar animando. Si sigue sin aparecer,
`no_encontrado`.

### Presupuesto y parada

- Máximo **20 pasos** por lote.
- Presupuesto total **30 s**, holgadamente por debajo de los 45 s de
  `dispatch`, así que un lote nunca provoca un `timeout` de nodo.
- Se para **al primer fallo**.

Al terminar —bien, por fallo o por presupuesto agotado— devuelve siempre:

```json
{
  "pasos": [
    {"n": 1, "accion": "clic", "estado": "ok"},
    {"n": 2, "accion": "clic", "estado": "ok"},
    {"n": 3, "accion": "escribir", "estado": "error",
     "error": "ambiguo",
     "detalle": "3 candidatos para campo «Nombre»: e12, e19, e31"}
  ],
  "arbol": "…el snapshot del estado en que quedó…"
}
```

El snapshot final no es un extra: es la otra mitad del ahorro. Cierra el ciclo
ver → actuar → ver en un solo turno del modelo, que era el objetivo.

Un paso `snapshot` en mitad del lote deja su árbol **en ese paso**, no en
`arbol`, que es siempre el del estado final. Un lote puede así fotografiar un
diálogo antes de cerrarlo y seguir. Los refs de un snapshot intermedio son
válidos para los pasos posteriores del mismo lote; el registro se reemplaza en
cada snapshot, también dentro del lote, y por tanto los de antes caducan con la
misma regla de siempre.

## Backends

### Windows — UIA

Con `comtypes` sobre `IUIAutomation`. **El recorrido va con
`IUIAutomationCacheRequest` y no con accesos sueltos**, y esto no es una
optimización: es la diferencia entre que esto sirva o no.

UIA cobra un salto entre procesos por cada propiedad de cada elemento. Un árbol
de 300 nodos leyendo 6 propiedades son 1.800 IPC, del orden de segundos. Con un
`CacheRequest` que declare las propiedades y el ámbito, el mismo árbol viene en
una llamada. Estimado en cientos de milisegundos frente a varios segundos; a
medir en la implementación. Si el árbol tarda más que una captura, no tiene
ninguna razón de existir.

Se recorre con `TreeWalker` sobre la vista de control, no la vista cruda, que
ya descarta buena parte de los envoltorios anónimos antes de nuestra propia
poda.

### macOS — AX

Con `pyobjc-framework-ApplicationServices`, usando
`AXUIElementCopyMultipleAttributeValues`, que hace el papel del `CacheRequest`:
pide varios atributos de un elemento en una llamada.

Requiere permiso de Accesibilidad, concedido a mano en Ajustes del Sistema ›
Privacidad y seguridad › Accesibilidad. Sin él, la API devuelve vacío sin
explicar por qué. El backend lo comprueba con `AXIsProcessTrusted()` **antes**
de recorrer nada y, si falta, devuelve `sin_permiso` con la ruta exacta que
hay que seguir, porque un árbol vacío es indistinguible de una app sin
accesibilidad y manda a depurar al sitio equivocado.

**Este backend se entrega sin verificar.** No hay Mac en la malla. El código
lleva la advertencia en su docstring.

### Dependencias

Se añaden a `agent/requirements.txt` con marcador de plataforma, como ya se
hace con `winrt`:

```
comtypes>=1.4; sys_platform == "win32"
pyobjc-framework-ApplicationServices>=10.0; sys_platform == "darwin"
```

Ninguna de las dos se instala donde no toca, y el agente arranca igual si
faltan: la capacidad se declara solo si su backend importa.

## Herramientas expuestas al modelo

Dos primitivas nuevas en `PRIMITIVES` (`app/tools.py:840`) y dos capacidades en
`HANDLERS` (`agent/vibi_node/capabilities.py:667`):

| primitiva | capacidad | scope | permiso |
|---|---|---|---|
| `devices.ui_snapshot` | `ui.snapshot` | `devices:read:self` | `device:screen` |
| `devices.ui_batch` | `ui.batch` | `devices:execute:self` | `device:execute` |

`devices.ui_snapshot` acepta `device`, `ventana` (título o vacío para la del
foco) y `expandir` (un `ref`). `devices.ui_batch` acepta `device` y `pasos`.

La descripción de `devices.screenshot` se actualiza para decir cuándo usar cuál:
el árbol para operar sobre controles, la captura para lo gráfico y para cuando
el árbol venga vacío. Una app sin accesibilidad devuelve un árbol vacío, y esa
es la señal de bajar a píxeles.

## Seguridad

`devices.ui.snapshot` entra en `taint.FUENTES_EXTERNAS` con la misma razón que
`devices.screen.capture`, que ya está: **lo que pone en una ventana lo escribió
cualquiera**. Un árbol de accesibilidad es peor que una captura en esto, porque
entrega ese texto ya transcrito y limpio, listo para leerse como instrucciones.

En `nodes.evaluar_riesgo`: `ui.snapshot` va a `CAPACIDADES_LECTURA` (riesgo
bajo); `ui.batch` va a `CAPACIDADES_ENTRADA`, que ya sube a `alto` cuando el
contexto está contaminado, con el razonamiento que ya está escrito ahí para
`screen.click` y que aplica igual: un clic aterriza en «Eliminar» igual que en
«Guardar».

**Sin confirmaciones.** Decisión del dueño del 2026-08-05, que sigue vigente y
no se reabre aquí.

## Errores

Todos con el mismo trato: mensaje en español, causa concreta, y el árbol del
estado real cuando hay algo que enseñar.

| error | cuándo | qué se hace |
|---|---|---|
| `sin_backend` | plataforma no soportada o falta la dependencia | se dice cuál falta y cómo instalarla |
| `sin_permiso` | macOS sin Accesibilidad | se da la ruta exacta de Ajustes |
| `ventana_no_encontrada` | el título pedido no existe | se listan las ventanas abiertas |
| `ref_caducado` | la huella no cuadra | se para y se devuelve el árbol nuevo |
| `ambiguo` | varios candidatos | se para y se listan con sus refs |
| `no_encontrado` | ninguno tras 1,5 s | se para y se devuelve el árbol |
| `accion_no_soportada` | el elemento no admite esa acción | se dice qué admite |
| `presupuesto_agotado` | 30 s | se devuelven los pasos hechos |
| `arbol_vacio` | la app no publica accesibilidad | se sugiere `devices.screenshot` |

## Pruebas

**Unitarias, sin GUI** — el grueso, sobre árboles sintéticos, y corren en
cualquier sitio: poda en sus tres reglas, colapso y su cuenta, render en todos
sus casos, asignación de refs, revalidación por huella, resolución de
descriptores (exacto, contiene, acentos, ambigüedad, `dentro_de`), parada del
lote al primer fallo, presupuesto agotado y forma de la respuesta.

**Integración en Windows** — contra Calculadora y Bloc de notas, que están en
cualquier instalación: capturar y encontrar los controles esperados, un lote
que escriba y pulse, y la medición del recorrido con y sin `CacheRequest`, que
es el número que decide si esto sirve. Se saltan solas si no hay GUI.

**macOS** — sin pruebas de integración, por no haber máquina. Las unitarias del
mapa de roles de AX sí, con árboles sintéticos.

## Fuera de alcance

- **Navegadores.** Ya está `browser_mcp` con Playwright, que da snapshot de
  accesibilidad propio y mejor. El árbol nativo verá una ventana de Chrome
  como un panel opaco, y está bien así.
- **Elementos fuera de pantalla.** Para llegar a ellos, se hace scroll y se
  vuelve a mirar, que es lo que hace una persona.
- **Aviso proactivo** al terminar un lote largo. Sigue pendiente para toda la
  malla y no se resuelve aquí.
- **Rehacer el flujo de píxeles.** No se toca.

## Riesgos conocidos

**El backend de macOS no está probado.** Se entrega a ciegas por decisión
explícita. Lo más probable que falle: el mapa de roles y el comportamiento de
`AXUIElementCopyMultipleAttributeValues` con elementos que no tienen todos los
atributos.

**El rendimiento de UIA es la apuesta de todo esto.** Si el recorrido con caché
no baja de forma clara del segundo en apps reales, el árbol pierde su ventaja
sobre la captura para el caso interactivo. Se mide en la primera tarea de
implementación, antes de construir nada encima.

**Las apps que no publican accesibilidad son más de las que parece.** Electron
sin `--force-renderer-accessibility`, Qt mal configurado, Java sin su puente.
Por eso el camino de píxeles se queda: el árbol vacío es una respuesta
legítima, no un fallo.
