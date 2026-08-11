# Vibi Cara: rediseño 3D con Three.js

## Objetivo

Rediseñar `vibi-cara.html` para que la cara de Vibi se renderice con Three.js en lugar de SVG/CSS, conservando su identidad de gata, la paleta nocturna actual y los cuatro estados existentes (`idle`, `listening`, `thinking`, `speaking`).

## Alcance

Arrancó como rediseño aislado de `vibi-cara.html`, pero tras validar el prototipo se decidió adoptar la cara 3D como la oficial de la PWA. El alcance final cubre por tanto dos piezas:

1. `vibi-cara.html` — el prototipo standalone, que se conserva como banco de pruebas visual con sus botones de estado.
2. La ruta `/cara` de la PWA — `FacePanel` deja de dibujar el SVG en línea y pasa a montar la escena 3D.

Ambas comparten geometría, poses y tiempos, pero no comparten código: el prototipo es autocontenido (Three.js por CDN) y la PWA lo importa desde npm. Al tocar uno hay que replicar el ajuste en el otro.

## Estructura en la PWA

- `frontend/src/lib/face3d.ts` — toda la escena de Three.js, sin dependencias de React. Expone `createFaceScene(container)`, que devuelve `{ setState, resize, dispose }` o `null` si no hay WebGL, más `supportsWebGL()`.
- `frontend/src/components/VibiFace.tsx` — envoltorio React mínimo: monta la escena al montar, le pasa `state`, la destruye al desmontar.
- `frontend/src/components/FacePanel.tsx` — conserva intacta la lógica de voz (captura, transcripción, locución, errores) y sustituye el SVG por `<VibiFace state={state} />`.

`VibiFace` se carga con `React.lazy` para que Three.js viaje en su propio chunk: solo se descarga al entrar en `/cara`, no en el arranque de la app.

Las reglas CSS del SVG (`.face-cat`, `.face-ear`, `.face-eye`, `.face-whiskers`, los `@keyframes` de la cara y las variables `--face-*`) se eliminan por quedar muertas. Sobreviven `.face-page`, `.face-stage`, `.face-halo` (el halo sigue siendo CSS, detrás del lienzo), `.face-feedback` y las reglas responsive.

## Decisiones

- Three.js se carga vía CDN como módulo ES (`import maps`), sin bundler ni paso de build, manteniendo el archivo autocontenido igual que hoy.
- La geometría de la cabeza se construye enteramente con primitivas de Three.js (esferas, conos, formas extruidas/tubulares) escritas directamente en el código. No se cargan archivos `.glb` ni modelos externos.
- El estilo visual es low-poly / toon: sombreado tipo cel-shading mediante `MeshToonMaterial` con un gradient map generado en un `<canvas>` en tiempo de ejecución (sin textura externa), más una técnica de contorno (outline) mediante una copia de cada malla ligeramente escalada, con culling de caras frontales y color oscuro sólido, renderizada detrás.
- El fondo (degradado radial, halo, viñeta) permanece como CSS de página; el `WebGLRenderer` se configura con canvas transparente (`alpha: true`) superpuesto encima.
- Se conserva la API pública actual: la función global `setEstado(estado)`, los botones de demo y la etiqueta de estado (`#etiqueta`). Cualquier código externo que hoy invoque `setEstado` seguirá funcionando igual.
- Se respeta `prefers-reduced-motion`: las animaciones ambientales continuas (flotar, parpadear, mirar de reojo, orejas, chispa) se desactivan o reducen a una pose estática por estado.
- Si el navegador no soporta WebGL, se muestra un mensaje de texto breve en lugar de un canvas en blanco o un error silencioso.

## Arquitectura

Un único archivo HTML con:

1. **CSS de página** (sin cambios de fondo/vignette/halo respecto al actual).
2. **Escena Three.js**: `Scene`, `PerspectiveCamera` encuadrando la cabeza, `WebGLRenderer` transparente ajustado al contenedor `.escenario` existente (con listener de resize), luz ambiental + una luz direccional para el sombreado toon.
3. **Construcción procedural de la cabeza** en un grupo `catHead`, con subgrupos independientes para poder animar cada parte:
   - `head` (esfera/icosaedro escalado)
   - `earLeft` / `earRight` (conos, cada uno con su propio pivote de rotación)
   - `eyeLeft` / `eyeRight` (socket esférico + pupila + doble brillo, igual que el SVG actual)
   - `cheekLeft` / `cheekRight` (rubor)
   - `nose`, `mouth` (curva/tubo, con variante "hablando" para speaking)
   - `whiskersLeft` / `whiskersRight` (cilindros finos)
   - `sparkle` (octaedro sobre la cabeza)
   - `thinkingDots` (tres esferas pequeñas, ocultas salvo en `thinking`)
   - `listeningRing` (toro plano, oculto salvo en `listening`)
4. **Máquina de estados** en JS puro: un objeto que, dado el estado activo, fija los parámetros objetivo de cada subgrupo (rotación, escala, posición, visibilidad) y un bucle de animación (`renderer.setAnimationLoop`) que interpola hacia esos objetivos y aplica los ciclos continuos correspondientes (parpadeo, bob, twinkle, etc.), replicando los tiempos/curvas que ya existen en los `@keyframes` actuales.
5. **Fallback sin WebGL**: comprobación simple al iniciar; si falla, se sustituye el contenedor de la escena por un mensaje de texto.

## Comportamiento por estado

Mismos disparadores y semántica que la versión SVG actual, traducidos a transformaciones 3D:

- **idle**: bob/flotación suave de `catHead`; parpadeo periódico (escala Y de los ojos); mirada de reojo aleatoria (offset de pupilas); flick ocasional de oreja izquierda; chispa titilando. Con `prefers-reduced-motion`, estas animaciones continuas se detienen.
- **listening**: `catHead` se inclina; ambas orejas rotan hacia arriba/afuera; ojos escalados hacia arriba; rubor visible; `listeningRing` pulsante visible.
- **thinking**: ojos con `scaleY` reducido (entrecerrados); pupilas desplazadas arriba y al lado; `catHead` inclinada al lado opuesto de listening; `thinkingDots` visibles con rebote/fade escalonado; boca torcida.
- **speaking**: ojos cambian a variante feliz (arco), boca en bucle abierto/cerrado (escala), `catHead` con rebote, bigotes oscilando, rubor intenso.

Las transiciones entre estados se animan con interpolación (lerp/easing), no con cortes instantáneos, para mantener la sensación de vida que tiene la versión actual.

## Pruebas y verificación

En la PWA, Vitest cubre `face3d` y `VibiFace` en jsdom, donde no hay WebGL: que `supportsWebGL()` dé `false`, que `createFaceScene` devuelva `null` en vez de lanzar y no deje lienzos colgados, que la escena se monte una sola vez aunque cambie el estado, y que se destruya al desmontar. La escena renderizada en sí no se puede comprobar en jsdom; eso queda en la revisión visual.

El prototipo standalone no tiene suite automatizada (no forma parte del pipeline). Su verificación es manual:

- Abrir `vibi-cara.html` directamente en el navegador.
- Click por los cuatro botones de demo y confirmar que cada estado produce las animaciones descritas sin errores en consola.
- Verificar el comportamiento con `prefers-reduced-motion` activado (emulación en devtools).
- Redimensionar la ventana y confirmar que el canvas se reajusta sin distorsión.
- Simular ausencia de WebGL (o revisar el código del check) para confirmar que el fallback de texto aparece en vez de un canvas roto.

## Fuera de alcance

- Cargar modelos 3D externos (`.glb`/`.fbx`) o texturas externas.
- Unificar el prototipo y la PWA en un único origen de código.
- Postprocesado avanzado (bloom, SSAO, sombras proyectadas).
- Física, colisiones o interacción por arrastre/orbit controls.
- Sonido o integración con el flujo de voz real (eso vive en el diseño de `/cara` en React).