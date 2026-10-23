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
| **Fuentes reales** | `estudio_atlas_buscar` + `estudio_atlas`, `estudio_molecula`, `estudio_modelo` | Geometría que no se puede inventar: ~3.900 piezas del atlas Z-Anatomy, moléculas de PubChem, modelos curados. |
| **Atajos** | `estudio_funcion`, `estudio_sucesion`, `estudio_superficie`, `estudio_marca`, `estudio_simulacion`, `estudio_grafo` + `estudio_recorrido`, `estudio_ordenacion` | Lo frecuente en matemáticas, física y algoritmos, en una llamada. |
| **Explicación** | `estudio_paso`, `estudio_ir_a_paso`, `estudio_parametro` | Pasos con qué aparece y qué se señala, preguntas de predicción, deslizadores. |
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
