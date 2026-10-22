# Estudio — el engine visual de Vibi

Estudio es una sección de Vibi donde el agente **explica conceptos montando
escenas interactivas** (gráficas, simulaciones físicas, algoritmos animados,
moléculas, modelos 3D) en vez de escribirlas en texto.

La idea central: **el modelo nunca escribe código gráfico**. Llama a
herramientas de alto nivel (`estudio_funcion`, `estudio_simulacion`,
`estudio_recorrido`…) que validan, calculan y dejan la escena descrita como
datos. La PWA solo pinta esos datos.

## Por qué así

Un LLM que escribe three.js a pelo falla de formas conocidas: código que no
compila, escalas absurdas, etiquetas que se pisan y, sobre todo, contenido
inventado (un corazón con las cavidades mal, un periodo de péndulo recordado
mal). Estudio invierte el reparto:

| Lo hace el engine | Lo hace el modelo |
|---|---|
| Evaluar fórmulas, integrar la física, ejecutar los algoritmos | Elegir qué enseñar y en qué orden |
| Validar y explicar cada error («escribe 2*x, no 2x») | Redactar el texto de cada paso |
| Traer geometría real (PubChem, catálogo curado) | Formular preguntas de predicción |
| Componer y encuadrar la escena | Nada de coordenadas ni de cámara |

Cada elemento lleva su **procedencia** (`engine`, `pubchem`, `catalogo` o
`modelo`) y la interfaz la enseña: «Calculado», «PubChem», «Catálogo» o
«Vibi» (texto redactado por el modelo). Y cada herramienta **devuelve los
números calculados** para que el modelo explique con ellos en vez de con lo
que recuerda.

## Arquitectura

```
modelo ──MCP──▶ tools.PRIMITIVES["estudio.*"] ──▶ app/estudio/
                       (validación + auditoría)        │
                                                       ├─ expresiones.py  fórmulas sin eval
                                                       ├─ fisica.py       modelos y magnitudes
                                                       ├─ algoritmos.py   grafos y ordenación
                                                       ├─ moleculas.py    PubChem + locales
                                                       ├─ modelos.py      catálogo glTF
                                                       └─ escena.py       estado + difusión
                                                                │
                                         WebSocket "estudio_escena" │
                                                                ▼
                         frontend/src/pages/EstudioPage.tsx (React Three Fiber)
```

- Las herramientas son **primitivas normales**: llegan a Claude por el MCP
  interno y a `agy` por el puente MCP sin tocar ninguno de los dos motores, y
  pasan por la misma auditoría que el resto.
- La escena es un JSON por usuario (`data/estudio/escenas/<usuario>.json`).
  Cada herramienta la edita con `escena.editar()`: si falla a mitad, no se
  guarda nada.
- Cada cambio viaja entero por el WebSocket a todas las ventanas del usuario.
  `estudio_ir_a_paso` mueve a todas a la vez (útil por voz o en clase).
- Las fórmulas se validan en el servidor y se guardan en forma canónica; el
  cliente las evalúa con mathjs para que los deslizadores respondan sin ir y
  volver al servidor.

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `estudio_nueva_escena` | Crea o vacía la escena (2d/3d, rangos). Su descripción lleva el flujo de trabajo. |
| `estudio_ejes` | Ajusta rangos o los oculta. |
| `estudio_parametro` | Deslizador que el alumno mueve; se usa como variable en fórmulas o simulaciones. |
| `estudio_funcion` | `y = f(x)`. Devuelve muestras y avisa si se sale de los ejes. |
| `estudio_sucesion` | Términos o sumas parciales (barras, puntos, línea). |
| `estudio_superficie` | `z = f(x, y)` coloreada por altura. |
| `estudio_marca` | Punto, vector o etiqueta; coordenadas con deslizadores. |
| `estudio_simulacion` | Péndulo, muelle, tiro parabólico u onda. Devuelve periodos, alcances… |
| `estudio_grafo` + `estudio_recorrido` | Grafo y Dijkstra/BFS/DFS animados paso a paso. |
| `estudio_ordenacion` | Burbuja, selección, inserción, quicksort, mergesort animados. |
| `estudio_molecula` | Geometría 3D real de PubChem (nombre en inglés o CID). |
| `estudio_modelo` | Modelo glTF del catálogo curado, con partes resaltables. |
| `estudio_paso` | Paso de la explicación: texto, qué aparece/desaparece/se resalta, pregunta de predicción. |
| `estudio_ir_a_paso` | Lleva a todas las pantallas a un paso. |
| `estudio_quitar` | Quita un elemento o deslizador (y limpia los pasos que lo nombraban). |
| `estudio_ver_escena` | Resumen de la escena. |
| `estudio_validar` | Referencias rotas, deslizadores sin uso, elementos que nunca se ven, curvas fuera. |
| `estudio_captura` | Imagen del lienzo para que el modelo revise su propia escena. |

## Para la demo

Con la sección **Estudio** abierta, en el chat de la derecha:

1. *«Explícame por qué la serie armónica diverge»* — barras de 1/n, sumas
   parciales y ln n + γ, con un deslizador para N y una pregunta de predicción.
2. *«Quiero jugar con un péndulo: ¿por qué el periodo depende del ángulo?»* —
   simulación con deslizadores; el panel compara T medido, T exacto (integral
   elíptica) y la aproximación de pequeñas oscilaciones.
3. *«Enséñame Dijkstra con un ejemplo y compáralo con BFS»* — el grafo se
   anima nodo a nodo con las distancias.
4. *«Enséñame la cafeína»* — geometría de PubChem, girando.
5. *«¿Qué forma tiene z = sin(x)·cos(y)?»* — superficie 3D con un deslizador.

Una comparación que se ve en un minuto: pedir lo mismo a un LLM que escriba
three.js directamente y a Vibi con Estudio.

## Añadir modelos 3D (anatomía, piezas)

El engine no genera modelos: solo carga los que alguien ha revisado. Se dejan en
`data/estudio/modelos/` (junto a `vibi.db`) con un `catalogo.json`:

```json
[
  {
    "id": "corazon",
    "nombre": "Corazón humano",
    "archivo": "corazon.glb",
    "fuente": "Z-Anatomy, CC BY-SA 4.0",
    "partes": {
      "Left_atrium": "Aurícula izquierda",
      "Left_ventricle": "Ventrículo izquierdo"
    }
  }
]
```

`partes` asocia el nombre de cada malla del glTF con el nombre que ve el
alumno. El modelo puede resaltarlas con `estudio_modelo(resaltar=[...])` o en
un paso con `resaltar: ["corazon.Aurícula izquierda"]`. Sin modelos
instalados, la herramienta le dice al agente que no invente uno.

## Límites conocidos

- PubChem necesita red; sin ella solo están agua, metano, CO₂ y amoniaco.
- La captura es del lienzo WebGL: las etiquetas HTML y los controles no salen.
- El estado de los deslizadores es de cada ventana; lo que se sincroniza es la
  escena y el paso actual.

## Siguiente paso para el TFG: la evaluación

1. Un banco de 30–50 peticiones repartidas entre matemáticas, física,
   algoritmos y química.
2. Línea base: el mismo modelo escribiendo three.js directamente.
3. Métricas: escenas que se renderizan sin error, corrección (numérica donde
   se puede comprobar), iteraciones hasta una escena válida, tiempo.
4. Si da tiempo, un estudio pequeño con estudiantes (predecir-observar-explicar).
