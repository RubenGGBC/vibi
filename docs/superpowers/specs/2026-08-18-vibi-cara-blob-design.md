# La cara de Vibi, rediseñada como criatura que se transforma

Sustituye a `2026-08-03-vibi-cara-threejs-design.md`.

## 1. Qué se rediseña y por qué

Hoy la cara de Vibi es una gata 3D en Three.js: una esfera de cabeza con
hocico, orejas, párpados, cejas, coloretes y una boca de cinco formas, movida
por muelles. Son 1029 líneas en `lib/face3d.ts` y una dependencia de 687 kB
minificados (`three.module.min.js`).

El problema no es el gato: es que **la cara pone expresiones sobre una cabeza
que no se mueve**. Suben las cejas, cambia la boca, y la silueta se queda igual
haga lo que haga. Eso deja dos consecuencias:

- Los diecisiete estados se parecen entre sí. De lejos —y el companion se ve
  de lejos— un turno navegando y uno escribiendo son la misma mancha morada.
- Todo lo que Vibi sabe del turno se tira. `boundaries`, los `delta`, el
  `pong`, la fase de arranque, qué equipo ejecuta: llegan al frontend y nadie
  los mira.

El rediseño toma como referente **bloub** (`bloub.vercel.app`) y cambia el
principio: la criatura no gesticula, **se convierte en la cosa que significa**.

## 2. Qué se toma del referente y qué no

Se estudió el bundle de bloub. Lo que se adopta:

- **La silueta como 64 radios en polar.** Toda forma —cúpula, rectángulo,
  barra, triángulo, punto— es el mismo array de 64 números más
  `{rot, cx, cy, sx, sy}`. Morfar es interpolar 64 floats: no hay que emparejar
  paths ni contar nodos. Los 64 puntos pasan por Catmull-Rom convertido a
  Bézier (tensión 1/6) y salen como un único atributo `d`.
- **Los ojos sobre una esfera.** Dos puntos separados `separacion` grados sobre
  una esfera de radio 100, orientada por `{yaw, pitch, roll}`. La proyección
  devuelve el centro, el marco tangente 2×2 y la profundidad. Al girar la
  cabeza los ojos se achatan solos y el de detrás desaparece cuando la
  profundidad baja de 0.02. Esto es lo que separa mirar de deslizar dos óvalos.
- **La vida en reposo por ruido, no por muelles.** Deriva de 0.6 %,
  respiración de 3.4 s al 0.5 %, y cabeceo de ruido suave en tres frecuencias.
- **El horario de parpadeo pregenerado con semilla.** Parpadeos cada 1.9–4.6 s,
  con 18 % de probabilidad de doble; el párpado cierra en el 45 % del tiempo y
  abre en el 55 %. La asimetría es lo que lo hace parecer real.
- **Cero librería de animación.** Un `requestAnimationFrame` y aritmética.

Lo que **no** se adopta, con su motivo:

- **El buscador de contención de ojos.** bloub deja que el usuario combine
  cualquier cuerpo con cualquier animación, así que necesita resolver en tiempo
  de carga cuánto desplazar la cara para que los ojos no se salgan (12
  direcciones × 8 pasos de bisección). Vibi no tiene cuerpo elegible: las poses
  se escriben a mano y se escriben cabiendo. Se descarta.
- **`baseFace` / `baseBody`.** Son la mecánica del selector de bloub, para que
  la forma elegida asome durante las animaciones. Aquí no hay selector.
- **Los estados de escaparate** (`egg`, `hexagon`, `orbit`, `comet`, `burst`).
  Son demos sin significado. Vibi solo tiene gestos que quieren decir algo.

## 3. La identidad

Vibi deja de ser una gata y pasa a ser el robot de la referencia visual del
usuario, en versión blob:

- Cabeza en cúpula, más ancha arriba, con dos tetones a los lados.
- Dos ojos grandes y ovalados que ocupan media cara.
- **Una antena**: tallo fino y bola arriba.

La antena es deliberada. bloub tiene dos canales —silueta y mirada— y una
antena con inercia es un tercero que el referente no tiene: se desploma al
dormir, late en alerta, se queda apuntando adonde la cabeza ya no mira. Es lo
que impide que esto sea un calco.

**No hay boca, ni nariz, ni cejas, ni coloretes.** Cuantas más piezas tiene una
cara, menos importa que la silueta se deforme; y la silueta deformándose es
todo el punto.

### Paleta

| Elemento | Color | Nota |
|---|---|---|
| Cuerpo | `#A89BB0` | gris lavanda, fijo |
| Ojos | `#7ED321` | verde, fijo |
| Antena (bola) | `#D0021B` | rojo, fijo |

**El color no codifica el estado**: el gesto lo cuenta. El color solo se mueve
cuando el gesto lo pide — al caerse el canal se le apaga la luz de los ojos, y
poco más. Esto retira el trabajo de la coreografía de tonos que hoy vive en
`styles/companion.css` (`--acento` y compañía cambian de color en cada estado);
esas variables pasan a mandar solo intensidad de halo, no matiz.

## 4. Arquitectura

Se conserva la **forma** de la interfaz `FaceScene` —`setState`, `setPointer`,
`clearPointer`, `resize`, `dispose`— y se sustituye la implementación entera.
El único añadido es `setSenales` (§5). `VibiFace.tsx` apenas cambia: mismo
ciclo de vida, mismo `ResizeObserver`, mismo seguimiento de puntero.

El render es **imperativo, no React**: la escena posee los nodos SVG y les
escribe `d` y `transform` dentro del bucle de animación. Volver a renderizar
React a 60 fps para mover una forma sería trabajo tirado.

```
frontend/src/lib/face/
  estados.ts       tipos: FaceState, FaceVoiceState, FaceToolState, Senales
  radios.ts        el modelo polar: 64 radios, formas nombradas, lerp, contorno→path
  mirada.ts        proyección esférica de los ojos, párpados
  antena.ts        cadena de dos segmentos con muelle, y el desprendimiento de la bola
  vida.ts          ruido de reposo, respiración, horario de parpadeo con semilla
  gestos.ts        las 23 poses: (t: number) => Pose
  modificadores.ts las 6 señales vivas que se montan encima de la pose
  escena.ts        el bucle: estado → pose → morph → Pose final → atributos SVG
  index.ts         reexporta lo público
```

`lib/faceMotion.ts` sobrevive entero —muelles, ritmo de dibujo, seguimiento de
puntero, `pulso`, `acotar`— y se le añaden el ruido y el horario de parpadeo en
`vida.ts`. `lib/faceMood.ts` y `lib/faceTool.ts` conservan su papel; cambian
solo porque el vocabulario de estados se amplía (§6).

### El modelo de datos

```ts
interface Silueta {
  radii: number[];   // 64
  rot: number; cx: number; cy: number; sx: number; sy: number;
}

interface Ojo { w: number; h: number; inclinacion: number; abierto: number; }

interface Punto { x: number; y: number; r: number; opacidad: number; }
interface Arco { id: string; semilla: number; t: number; opacidad: number; }

interface Antena {
  largo: number;        // 1 = normal, 0 = retraída
  rigidez: number;      // cuánto sigue a la cabeza; bajo = se arrastra
  bolaSuelta: boolean;  // se desprende (pensar, alerta)
  bolaDestino?: { x: number; y: number };
  radioBola: number;
}

interface Pose {
  cuerpo: Silueta;
  mirada: { yaw: number; pitch: number; roll: number };
  separacion: number;          // grados entre ojos
  ojos: [Ojo, Ojo];
  alfaOjos: number;            // 0 en los gestos que se vuelven símbolo
  alfaCuerpo: number;
  antena: Antena;
  puntos: Punto[];             // partículas
  arcos: Arco[];               // estelas
}

interface Gesto {
  id: FaceState;
  duracion: number;            // segundos del ciclo
  morph: number;               // segundos de transición al entrar
  duracionMinima?: number;     // no se corta antes de esto
  parpadeaDentro: boolean;
  pose: (t: number) => Pose;
}
```

## 5. Las señales vivas

Se añade un método a `FaceScene`:

```ts
setSenales(senales: Senales): void

interface Senales {
  pasos: number;           // ChatRuntimeState.boundaries
  cadencia: number;        // deltas/s sobre una ventana móvil de 1.5 s
  retrasoCanal: number;    // ms desde el último pong
  remoto: string | null;   // nombre del equipo que ejecuta, o null
  pendientes: number;      // órdenes esperando permiso
  corte: number;           // timestamp del último boundary
}
```

`useFaceMood` las reúne —ya está suscrito al canal y a la caché— y las devuelve
junto al ánimo. Ninguna requiere tocar el servidor: **las seis ya llegan hoy** y
se descartan en el frontend.

Umbrales, para que no queden a interpretación:

| Señal | Rango que se mapea | Fuera de rango |
|---|---|---|
| `pasos` | 0 → 12 | satura en 12 |
| `cadencia` | 0 → 40 deltas/s | satura en 40 |
| `retrasoCanal` | 0 → 6000 ms | por encima manda `offline`, que lo decide `faceMood` |
| `pendientes` | 0 → 5 puntos | el sexto y siguientes no añaden punto |

`fase: "arranque"` pasa a emitir el gesto `arranque` desde `decidirAnimo`, con
la misma prioridad que hoy tiene `fase: "herramienta"`.

## 6. El vocabulario: 23 gestos

### Voz (4) + arranque (1)

| Gesto | Qué hace |
|---|---|
| `idle` | cúpula respirando, deriva de ruido, antena tiesa oscilando apenas |
| `arranque` | coge aire: se comprime y se expande una vez, la antena se yergue |
| `listening` | se inclina hacia ti y **la deriva se para** — atención es quietud. La antena se dobla hacia delante como una oreja que apunta |
| `thinking` | el cuerpo se deshace en **tres puntos**, y el tercero es **la bola de la antena, desprendida**, orbitando. Ojos apagados |
| `speaking` | la silueta late con la sílaba; la antena rebota medio golpe por detrás, por inercia |

### Herramientas (14)

Cada uno sale de una regla que ya existe en `faceTool.ts`. Hoy esas veinte
frases distintas se aplastan en nueve caras; aquí se reparten en catorce.

| Gesto | Reglas que lo activan | Qué hace el cuerpo |
|---|---|---|
| `searching` | `search_web`, `web_search`, `websearch` | se estira hacia fuera y barre el horizonte, antena arrastrando |
| `browsing` | `browser_`, `playwright`, `webfetch`, `read_url` | se aplana en rectángulo redondeado, ojos en zigzag de lectura |
| `rummaging` | `glob`, `grep`, `list_directory`, `files_search`, `search_file` | rebusca a golpes cortos, mirando abajo |
| `reading` | `read_file`, `view_file`, `read` | se estrecha y alarga como una hoja; barrido línea a línea con salto de renglón |
| `writing` | `write`, `edit`, `replace` | **la antena es el lápiz**: se inclina y garabatea, el cuerpo se ladea con ella |
| `noting` | `create_note` | igual pero breve y ligero: dos trazos y ya |
| `hacking` | `terminal`, `shell`, `bash`, `run_command`, `execute` | se vuelve rectángulo de terminal; los ojos se reducen a un cursor que parpadea |
| `peeking` | `screenshot`, `ui_snapshot` | se asoma por el borde: solo ojos y media cúpula |
| `handling` | `click`, `scroll`, `keyboard`, `ui_batch` | se asoma y actúa: la antena picotea hacia el punto |
| `launching` | `launch_app`, `open_url`, `open_path` | se agacha y sale disparada, la antena se queda atrás |
| `sending` | `send_file` | se estira de un lado a otro, suelta algo y vuelve |
| `reaching` | `pc_`, `devices` | se inclina hacia fuera de la ventana, la antena apunta al otro equipo |
| `vibing` | `media`, `youtube` | rebota al compás, antena de metrónomo |
| `working` | lo que no encaje | gira despacio, antena trazando un círculo |

### Avisos (4)

| Gesto | Qué hace |
|---|---|
| `waiting` | se encoge y **la antena se dobla en interrogación**; ojos grandes y fijos, sin deriva |
| `alert` | **se convierte en un `!`**: el cuerpo se estira en la barra y la bola de la antena baja a ser el punto |
| `pleased` | salta, se aplasta al caer, la antena rebota; ojos en arco |
| `offline` | se desinfla, la antena se desploma, los ojos se apagan a dos rendijas grises. **Sin respiración**: quieto de verdad |

`alert` es el resumen de la idea. bloub se vuelve un `!` y tiene que inventarse
el punto; Vibi ya lo lleva puesto en la cabeza.

## 7. Los seis modificadores

Un gesto no es solo una forma. Encima se montan las señales vivas, y eso es lo
que evita que hagan falta doscientas poses.

1. **Lastre del turno** — `pasos` (de `boundaries`) dice cuántos pasos lleva
   encadenados el turno. La bola de la antena se carga: crece hasta un 40 % y
   late más rápido, saturando hacia el paso 12. De un vistazo se distingue un
   turno de un paso de uno de doce. Hoy esto no se ve en ninguna pantalla.
2. **Latido real de tokens** — el pulso de `speaking` y de la fase de redactar
   lo marca `cadencia`, medida sobre los `delta` que llegan. Si el modelo se
   atasca, la cara se queda quieta, y esa quietud **es** la información. No hay
   seno inventado.
3. **Piloto del canal** — la bola late con el `pong`. Cuando `retrasoCanal`
   crece, el latido se arrastra y pierde brillo **antes** de que el canal se
   declare caído. Aviso temprano en vez de un `offline` de golpe.
4. **Aquí o allí** — con `remoto` no nulo, el cuerpo se inclina y la antena
   apunta **siempre al borde derecho**, sea cual sea el gesto. La dirección es
   fija y convencional a propósito: no sabemos dónde está físicamente el otro
   equipo, y fingir que sí sería inventarse información. Lo que se comunica es
   «esto pasa fuera», no «pasa allí». Distingue «lo está haciendo» de «se lo ha
   pedido a tu PC».
5. **Cuántos permisos** — la antena en interrogación se dobla más cuantas más
   órdenes se acumulan, con un punto orbitando por cada una hasta cinco.
6. **El corte con sentido** — `corte` marca el instante exacto del `boundary`.
   Los tres puntos de pensar **se recomponen y se lanzan** hacia el gesto nuevo,
   en vez de un fundido genérico.

## 8. Transiciones

Cada gesto declara su `morph` en segundos. La transición interpola los 64
radios, la mirada, la separación, los ojos y la antena. Como todas las formas
comparten topología, no hay caso especial: `alert` (una barra) sale de `idle`
(una cúpula) con el mismo `lerp` que cualquier otro par.

Regla de corte: un gesto con `duracionMinima` no se abandona antes de
cumplirla, aunque el estado ya haya cambiado. Sin esto, una ráfaga de eventos
deja la cara con tics a medias.

`prefers-reduced-motion` reduce las amplitudes a un tercio y apaga partículas y
estelas, pero **no congela la cara**: sigue habiendo cambio de forma, porque es
el canal que transporta el significado.

## 9. Qué desaparece

- `lib/face3d.ts` (1029 líneas) y sus dos tests, que solo cubren el fallback de
  WebGL.
- Las dependencias `three` y `@types/three`. `face3d.ts` es su único
  importador, así que la retirada es limpia.
- `supportsWebGL()` y toda la rama de «no hay escena»: `createFaceScene` puede
  devolver `null` y `VibiFace` tiene que soportarlo. Con SVG no hay contexto que
  pueda faltar, y esa rama entera se va.
- La carga diferida de `VibiFace` en `FacePanel` deja de tener motivo (existía
  para que Three.js viajara en su propio chunk), pero se mantiene: no molesta.

## 10. Pruebas

El modelo polar es aritmética pura, así que casi todo se prueba sin DOM. Es una
mejora grande respecto a los dos tests actuales.

- **`radios.ts`** — toda forma nombrada tiene exactamente 64 radios; el `lerp`
  entre dos formas devuelve 64; morfar de A a A es la identidad; el path
  generado empieza en `M` y cierra en `Z`.
- **`mirada.ts`** — a `yaw` 0 los dos ojos salen simétricos; con `yaw` grande
  uno cae por debajo del umbral de profundidad; la elipse se achata al girar.
- **`antena.ts`** — el muelle converge y no diverge con delta grande; soltar la
  bola no la teletransporta.
- **`vida.ts`** — el horario de parpadeo es determinista con la misma semilla;
  sobre 500 parpadeos la proporción de dobles cae cerca del 18 %; el cierre es
  más rápido que la apertura.
- **`gestos.ts`** — existe un gesto por cada `FaceState`, sin huecos; en los
  cíclicos `pose(0)` y `pose(duracion)` coinciden.
- **`modificadores.ts`** — funciones puras: el lastre satura, el retraso del
  canal degrada el brillo de forma monótona.
- **`faceTool.ts`** — se amplía el test existente con las reglas nuevas.

## 11. Fases

El trabajo es grande y hay un orden que deja algo utilizable en cada corte. Va
aquí y no en el plan porque condiciona el diseño: cada fase tiene que ser
completa por sí sola.

1. **El motor.** `radios.ts`, `mirada.ts`, `antena.ts`, `vida.ts`, `escena.ts`,
   más `estados.ts` con el vocabulario ya ampliado. Solo cinco gestos —`idle`,
   `listening`, `thinking`, `speaking`, `offline`— y el resto apuntando a
   `working`. Al final de esta fase Three.js ya está fuera y la cara funciona.
2. **El vocabulario.** Los dieciocho gestos restantes y la ampliación de
   `faceTool.ts` con sus reglas nuevas.
3. **Las señales.** `modificadores.ts`, `setSenales`, y la recolección en
   `useFaceMood`. Es lo único que toca la fontanería de eventos, y va última a
   propósito: si algo se tuerce aquí, la cara ya está entera sin ello.

## 12. Fuera de alcance

- No se toca el servidor. Las seis señales ya llegan.
- No se toca `faceMood.ts` en su lógica de prioridades, solo en el vocabulario.
- El halo, el aura y el anillo del companion siguen donde están; pierden el
  matiz por estado y conservan la intensidad.
