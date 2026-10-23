# Estudio — el engine visual de Vibi

Estudio es una sección de Vibi donde el agente **explica cualquier cosa
montando escenas interactivas**: gráficas, mecanismos animados, sistemas
dinámicos, algoritmos, moléculas o anatomía real, en vez de describirlas en
texto.

## La idea

El engine no sabe qué es un corazón, un péndulo o un sistema solar. Le da al
agente **piezas generales** y **fuentes de datos reales**, y el agente compone
con ellas lo que le pidan. El modelo **nunca escribe código gráfico**: llama a
herramientas que validan, calculan y dejan la escena descrita como datos. La
PWA solo la pinta.

| Capa | Herramientas | Qué aporta |
|---|---|---|
| **Piezas generales** | `estudio_objeto`, `estudio_sistema` | Formas anidables cuyas propiedades son fórmulas con deslizadores, tiempo y variables; ecuaciones diferenciales que integra el engine. Con esto se compone cualquier visualización. |
| **Fuentes reales** | `estudio_atlas_buscar` + `estudio_atlas`, `estudio_molecula`, `estudio_modelo`, `estudio_biblioteca` | Geometría que no se puede inventar: ~3.900 piezas del atlas Z-Anatomy, moléculas de PubChem, modelos curados y ~1.400 objetos del mundo (Kenney, CC0). |
| **Atajos** | `estudio_funcion`, `estudio_sucesion`, `estudio_superficie`, `estudio_marca`, `estudio_simulacion`, `estudio_grafo` + `estudio_recorrido`, `estudio_ordenacion` | Lo frecuente en matemáticas, física y algoritmos, en una llamada. |
| **Explicación** | `estudio_paso`, `estudio_ir_a_paso`, `estudio_parametro` | Pasos con su idea, una tarea para el alumno, qué aparece y qué se señala, preguntas de predicción con pistas, deslizadores. |
| **Revisión** | `estudio_validar`, `estudio_ver_escena`, `estudio_captura` | Referencias rotas, cosas fuera de cuadro, una foto del lienzo para que el agente se revise. |

### Lo que el engine garantiza

- **Validación con mensajes que dicen qué cambiar.** «escribe 2*x, no 2x»,
  «para caja, tamano es [ancho, alto, fondo]», ««Ventrículo central» no
  existe; tiene: …».
- **Números calculados de vuelta.** Cada herramienta devuelve lo que pasa de
  verdad (valores, rangos, periodos, si un sistema diverge) para que el agente
  lo cuente sin inventar. Un sistema caótico o amortiguado no se presenta como
  periódico.
- **Procedencia de cada elemento.** «Calculado» (lo evalúa el engine),
  «PubChem» / «Catálogo» (datos de una fuente) o «Vibi» (lo ha compuesto el
  modelo). Componer libremente está permitido; lo que no se hace es presentar
  como verificado algo que no lo está.

## Vibi como tutor

Vibi no presenta un tema: da la clase. Lleva el ritmo, le pide cosas al
alumno y adapta lo que viene a lo que responde.

- **Cómo se da la clase.** `estudio_nueva_escena` devuelve `como_tutor`, las
  reglas para el modelo: una pregunta de diagnóstico si no está claro el
  nivel; de 3 a 7 pasos con una idea cada uno; primero lo que se ve y después
  la fórmula; algo que hacer en cada paso, y un cierre con resumen y pregunta
  de comprobación. Van en la respuesta y no en la descripción para llegar
  justo cuando se empieza a montar.
- **Un paso** tiene `texto` (lo que le cuenta Vibi, una o dos frases), `idea`
  (lo que tiene que quedarse, destacado), `tarea` (lo que hace el alumno) y
  una pregunta opcional con `pistas`. Cada fallo destapa la pista siguiente;
  acertar, o fallar con las pistas gastadas, enseña la explicación.
  `estudio_paso` y `estudio_validar` avisan de pasos largos, sin idea o de una
  clase que no pide nada.
- **Lo que hace el alumno** se guarda en `progreso`: hasta qué paso ha llegado
  y qué ha elegido en cada pregunta (`POST /api/estudio/respuesta`). No sube
  la versión de la escena y viaja a todas sus ventanas como
  `estudio_respuesta`. El modelo lo lee en `estudio_ver_escena`.
- **Un solo sitio para la clase** (`components/estudio/Tutor.tsx`): una
  columna a la derecha del lienzo con el zorro (`FoxVibi`, los sprites de
  `vibiNewDesign`), un bocadillo con lo que acaba de decir Vibi, el paso
  actual y una caja para escribirle. El chat lateral queda cerrado: es para
  ver la conversación entera, no para dar la clase.
- **Todo lo que el alumno dice desde Estudio** (escrito, por voz o con «No lo
  entiendo», «¿Por qué?» y «¿Repasamos?») lleva delante «(Estudio)» o
  «(Estudio, paso N)». Las reglas de los dos motores (`app/estudio/turno.py`)
  le dicen al modelo que eso se contesta montando la escena: con solo la
  descripción de la herramienta, un modelo pequeño contestaba con texto.
- **Vibi habla** (`lib/estudio/vozTutor.ts`) si la voz está activa (se
  recuerda por navegador): al cambiar de paso cuenta el texto, la tarea y la
  pregunta; al responder dice la pista o la explicación, y lo que contesta el
  agente lo va diciendo mientras lo escribe. Si el agente está en mitad de un
  turno, el paso no se narra. Tocar al zorro abre el micro (`/api/voz` con
  el prefijo).
- Mientras Vibi prepara la respuesta, lo que había en el lienzo se vela hasta
  que la escena cambie: no se lee como la respuesta.

## Arquitectura

```
modelo ──MCP──▶ tools.PRIMITIVES["estudio.*"] ──▶ app/estudio/
                       (validación + auditoría)        │
                                                       ├─ composicion.py  objetos, sistemas, atlas
                                                       ├─ dinamica.py     integración RK4 y su resumen
                                                       ├─ expresiones.py  fórmulas sin eval
                                                       ├─ atlas.py        índice + extracción con Blender
                                                       ├─ moleculas.py    PubChem + locales
                                                       ├─ fisica.py, algoritmos.py, modelos.py
                                                       └─ escena.py       estado, persistencia, difusión
                                                                │
                                         WebSocket "estudio_escena" │
                                                                ▼
                         frontend/src/pages/EstudioPage.tsx (React Three Fiber)
```

- Las herramientas son primitivas normales: llegan a Claude por el MCP interno
  y a `agy` por el puente MCP, con la misma auditoría que el resto.
- La escena es un JSON por usuario; cada herramienta la edita en una
  transacción (si falla a mitad, no se guarda nada) y la escena viaja entera
  por el WebSocket a todas las ventanas.
- Las fórmulas se validan en el servidor y se guardan en forma canónica. El
  cliente las evalúa con mathjs en cada fotograma, e integra los sistemas en
  vivo con el mismo RK4 que usó el servidor para validarlos.

## Atlas anatómico

El índice (`app/estudio/atlas/indice.json`, versionado) lista las ~3.900 piezas
de Z-Anatomy con su sistema y sus grupos: el agente busca en inglés («kidney»,
«brachial plexus») y puede cargar piezas sueltas o grupos enteros
(«Urinary system», «Heart», «Bones of hand»). La geometría se extrae **bajo
demanda** del `.blend` del atlas con Blender sin interfaz, en un subproceso, y
queda en caché (`data/estudio/atlas/`). La primera extracción tarda unos
segundos; las siguientes, nada.

Para activarlo:

```bash
scripts/estudio_preparar_atlas.sh        # descarga el atlas e instala bpy (Python 3.11)
# y añade al .env las dos líneas que imprime:
ESTUDIO_ATLAS_BLEND=…/Startup.blend
ESTUDIO_BLENDER_PYTHON=…/blender-venv/bin/python
```

Sin eso, el agente puede buscar en el atlas pero no cargar, y la herramienta
se lo dice para que no invente.

El corazón viene además ya extraído en `app/estudio/modelos_incluidos/`
(`estudio_modelo`), para que la demo funcione sin instalar nada.

Atribución: Z-Anatomy (CC BY-SA 4.0), derivado de BodyParts3D (The Database
Center for Life Science, CC BY-SA 2.1 Japan).

## Biblioteca de objetos

Un coche, un cohete o una mesa compuestos con cajas y cilindros salen mal: el
modelo coloca geometría por coordenadas a ciegas (ruedas de pie, flechas
metidas en la carrocería). Para los objetos del mundo hay una biblioteca de
modelos hechos por personas: los kits 3D de [Kenney](https://kenney.nl), CC0
(vehículos, espacio, barcos y cañones, trenes, prototipos, herramientas,
muebles, comida, naturaleza y plataformas).

- `estudio_biblioteca` busca por palabras en inglés (entiende las españolas
  más comunes) y devuelve ids, medidas y partes con nombre.
- `estudio_objeto` con `forma: "modelo"` lo pone en la escena: `tamano` es su
  lado más largo, `posicion` el centro de su base, y lo demás (fórmulas,
  `padre`, estela) funciona igual que con cualquier forma. `girar_partes` gira
  partes sobre su eje (las ruedas de los coches de Kenney son nodos propios
  con el pivote en el eje) y los pasos pueden señalar partes:
  `resaltar: ["coche.wheel-front-left"]`.
- El índice (`app/estudio/biblioteca/indice.json`) va versionado; la geometría
  se descarga **bajo demanda**, el kit entero la primera vez, a
  `data/estudio/biblioteca/`, con las texturas metidas dentro de cada `.glb`.
  `scripts/estudio_preparar_biblioteca.py` descarga todo de golpe (≈40 MB) y
  regenera el índice.
- **Articulaciones** (`articulaciones` en `estudio_objeto`): partes que giran
  (bisagras, ejes) o se deslizan (cajones), con fórmula y topes. Kenney pone
  el pivote en la bisagra, así que basta con el eje; la búsqueda dice cuáles
  son articulables (`articulables`). `girar_partes` es una articulación de
  giro sin topes. Con topes, el alumno también la mueve con un deslizador.
- `estudio_editar_objeto` cambia solo lo que se le pasa de un objeto (también
  `colores_partes` y `ocultar_partes`) y conserva el resto.

### Más allá de Kenney

Tres fuentes más, en este orden de preferencia, todas guardadas después en
`data/estudio/biblioteca/` como un modelo más (`externos.json`):

| Fuente | Qué aporta | Necesita | Procedencia |
|---|---|---|---|
| **Sketchfab** (`sketchfab.py`) | Modelos realistas CC0 y CC BY de casi cualquier cosa | `SKETCHFAB_TOKEN` para descargar (buscar es anónimo) | Catálogo, con título, autor, licencia y enlace |
| **PartNet-Mobility** (`urdf.py`) | Objetos de casa con articulaciones anotadas (puertas, cajones, tapas) | Descargarlos de sapien.ucsd.edu e importarlos con `scripts/estudio_importar_urdf.py` | Catálogo |
| **Generados con IA** (`generacion.py`) | Lo que no existe en ninguna biblioteca, desde una descripción (Hunyuan3D en fal.ai) | `FAL_KEY`; cuesta dinero, con tope diario | **Vibi**: forma aproximada, no verificada |

- Sketchfab solo deja pasar lo descargable, con licencia aceptada, menos de
  `ESTUDIO_SKETCHFAB_MAX_MB` y menos de 300.000 caras. Su cortafuegos (AWS WAF)
  desafía la huella TLS de Python: si llega el reto, la petición se repite con
  `curl`, que lo pasa.
- Un URDF se convierte a `.glb` con un nodo por articulación, con el pivote en
  su origen y el eje en su `y` local: en la escena sale articulado de serie,
  con los topes del archivo.
- Lo generado se pide una vez por descripción (la misma no se cobra dos veces)
  y, si tarda, sigue en segundo plano: la siguiente llamada lo recoge.

## Manipular con el ratón

Encima del lienzo hay una barra (`Manipulacion.tsx`) y, bajo la leyenda, la
tarjeta de lo elegido:

- **Elegir**: un clic elige un objeto; otro clic sobre un modelo ya elegido
  elige la pieza. Esc suelta.
- **Mover, girar, escalar** (W, E, R): un gizmo. Al soltarlo se guarda en el
  servidor (`POST /api/estudio/objetos/{id}/ajuste`) y lo ven todas las
  ventanas. Un objeto entero solo se mueve si su colocación es fija (si
  depende de t o de un deslizador, el gizmo pisaría la animación); las piezas
  de un modelo, siempre. Se puede volver a como estaba. El agente ve en
  `estudio_ver_escena` qué ha colocado el alumno a mano.
- **Ocultar** (H), **ver solo esto**, **vista explosionada** (separa las
  piezas) y **corte** con un plano en x, y o z: solo cambian la vista de esa
  ventana, no la escena.
- **Articulaciones con topes**: un deslizador por cada una; lo fijado manda
  sobre la fórmula hasta que se suelta.

## Luz y sombras

El lienzo usa una luz de estudio generada en el cliente (`Environment` con
`Lightformer`, sin descargar HDRIs, para que funcione sin red), una luz
principal con sombras y, bajo el bloque de objetos, un suelo invisible que
solo recibe sombra: lo que flota se proyecta en algo y se lee qué está
delante de qué.

## Para la demo

Peticiones que se han probado en flujo sin preparar nada para ellas:

1. *«Enséñame el sistema solar interior»* — compuesto con `estudio_objeto`:
   órbitas animadas con estela, la Luna anidada en la Tierra y un deslizador de
   velocidad.
2. *«¿Qué es el atractor de Lorenz?»* — `estudio_sistema` con las ecuaciones,
   un punto que deja la «mariposa» y un deslizador para ρ.
3. *«Conejos y zorros: ¿cómo cambian las poblaciones?»* — Lotka-Volterra con
   su gráfica temporal; el engine detecta el periodo.
4. *«¿Cómo funciona el aparato urinario?»* — riñones, uréteres, vejiga y
   uretra extraídos del atlas, con un paso por tramo.
5. *«Enséñame el corazón por dentro»* — cavidades, válvulas y vasos
   señalados por su nombre.
6. *«¿Por qué diverge la serie armónica?»*, *«Dijkstra con un ejemplo»*,
   *«la molécula de cafeína»* — con los atajos.

Para el tutor, la comparación que se ve en un minuto: la misma petición a un
LLM que escribe three.js directamente y a Vibi con Estudio.

## Límites conocidos

- PubChem necesita red; sin ella solo están agua, metano, CO₂ y amoniaco.
- La biblioteca también: sin red solo están los kits ya descargados y los
  modelos ya importados.
- Los modelos de Sketchfab y los generados no traen el frente orientado: el
  agente tiene que mirarlos con una captura y girarlos.
- Las mallas generadas son una sola pieza: no se pueden articular ni señalar
  por partes.
- Ocultar, aislar, explosionar, cortar y los deslizadores de las
  articulaciones son de cada ventana, como los deslizadores de la escena.
- La captura es del lienzo WebGL: las etiquetas HTML y los controles no salen.
- Los deslizadores son de cada ventana; lo que se sincroniza es la escena y el
  paso actual.
- Los tubos y toros se reconstruyen al mover deslizadores, no en cada
  fotograma.

## Siguiente paso para el TFG: la evaluación

1. Un banco de 30–50 peticiones de temas variados, **sin preparar el engine
   para ellas**.
2. Línea base: el mismo modelo escribiendo three.js directamente.
3. Métricas: escenas que se renderizan sin error, corrección (numérica donde
   se puede comprobar), iteraciones hasta una escena válida, tiempo, y cuántos
   elementos quedan marcados como verificados frente a compuestos.
4. Si da tiempo, un estudio pequeño con estudiantes (predecir-observar-explicar).
