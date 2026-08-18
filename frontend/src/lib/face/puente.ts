import type { Look } from "./bloub/engine";
import type { ExpressionId } from "./bloub/expressions";
import { profileFromPolygon, unionOfCirclesProfile } from "./bloub/shape";
import type { StateId } from "./bloub/states";
import type { FaceState } from "./estados";

/**
 * De lo que Vibi está haciendo a lo que el motor de bloub tiene que dibujar.
 *
 * **Aquí no se inventa ni una medida.** Esa fue la lección cara: la primera
 * versión de esta cara la dibujé a ojo y los ojos salieron tres veces y media
 * más anchos de lo que toca, mirando de frente en vez de con el escorzo que les
 * da carácter. Las buenas están en `bloub/`, sacadas fotograma a fotograma del
 * vídeo de referencia: las proporciones del rostro, las quince animaciones y
 * las dieciséis expresiones con nombre. Este módulo solo **elige** entre ellas.
 *
 * Cada estado de Vibi se resuelve con tres palancas del motor y ninguna más:
 *
 * - **el estado base**, cuando ya existe una animación suya que significa eso
 *   —pensar son tres puntos, la alerta es un `!`, dormir es encogerse—;
 * - **la forma**, para las familias de herramienta que se leen por la silueta:
 *   navegar es una ventana, leer es una hoja;
 * - **la expresión y la mirada**, para lo que se cuenta con los ojos.
 *
 * Las dos últimas solo surten efecto sobre los estados que el motor marca como
 * reemplazables —en la práctica, `idle`—, y por eso las familias de herramienta
 * cuelgan de ahí mientras los gestos con significado propio conservan intacta
 * su expresión medida.
 */

export interface Interpretacion {
  /** El estado del catálogo de bloub que se pone. */
  base: StateId;
  /** Perfil de radios que sustituye el cuerpo, o `null` para el suyo. */
  forma: number[] | null;
  /** Cuál de sus expresiones con nombre, o `null` para la de reposo. */
  expresion: ExpressionId | null;
  /** Adónde mira a lo largo del ciclo, o `null` para su deriva libre. */
  mirada: ((t: number) => Look) | null;
}

/* ------------------------------------------------------------ siluetas */

/** El contorno de un rectángulo con las esquinas redondeadas. */
function rectanguloRedondeado(ancho: number, alto: number, radio: number) {
  const hx = ancho / 2;
  const hy = alto / 2;
  const r = Math.min(radio, hx, hy);
  const esquinas = [
    { cx: hx - r, cy: hy - r, desde: 0 },
    { cx: -(hx - r), cy: hy - r, desde: Math.PI / 2 },
    { cx: -(hx - r), cy: -(hy - r), desde: Math.PI },
    { cx: hx - r, cy: -(hy - r), desde: (3 * Math.PI) / 2 },
  ];
  const puntos = [];
  for (const e of esquinas) {
    for (let i = 0; i <= 8; i += 1) {
      const a = e.desde + ((Math.PI / 2) * i) / 8;
      puntos.push({ x: e.cx + Math.cos(a) * r, y: e.cy + Math.sin(a) * r });
    }
  }
  return puntos;
}

/** Una ventana: navegar y el terminal. Ancha y tumbada. */
const VENTANA = profileFromPolygon(rectanguloRedondeado(2.05, 1.28, 0.26), 0, 0);

/** Una hoja de papel: leer. Estrecha y alta. */
const HOJA = profileFromPolygon(rectanguloRedondeado(1.12, 1.82, 0.14), 0, 0);

/** Estirada a los lados: buscar fuera y alcanzar otro equipo. */
const ESTIRADA = unionOfCirclesProfile([
  { x: -0.32, y: 0, r: 0.79 },
  { x: 0.32, y: 0, r: 0.79 },
]);

/* -------------------------------------------------------------- miradas */

const TAU = Math.PI * 2;

/** Mira a un sitio y se queda. `inquietud` baja es atención. */
const fija =
  (yaw: number, pitch: number, inquietud = 0.35): ((t: number) => Look) =>
  () => ({ yaw, pitch, mix: 1, spin: 0, wander: inquietud });

/** Barrido de lado a lado: buscar. */
const barrido =
  (periodo: number, amplitud: number): ((t: number) => Look) =>
  (t) => ({
    yaw: Math.sin((t / periodo) * TAU) * amplitud,
    pitch: 0,
    mix: 1,
    spin: 0,
    wander: 0.2,
  });

/** Renglón a renglón con salto de línea: leer y navegar. */
const renglones =
  (periodo: number, lineas: number): ((t: number) => Look) =>
  (t) => {
    const avance = (t / periodo) % 1;
    const linea = Math.floor(avance * lineas);
    return {
      yaw: -0.75 + ((avance * lineas) % 1) * 1.5,
      pitch: -0.4 + (linea / Math.max(1, lineas - 1)) * 0.8,
      mix: 1,
      spin: 0,
      wander: 0.1,
    };
  };

/* ------------------------------------------------------------ el mapeo */

const suyo = (base: StateId): Interpretacion => ({
  base,
  forma: null,
  expresion: null,
  mirada: null,
});

const enReposo = (
  forma: number[] | null,
  expresion: ExpressionId | null,
  mirada: ((t: number) => Look) | null = null,
): Interpretacion => ({ base: "idle", forma, expresion, mirada });

/**
 * La tabla.
 *
 * Los estados que ya tienen animación propia en el catálogo la usan **tal
 * cual**: son gestos medidos, y cualquier cosa que yo les ponga encima los
 * empeora. Los de herramienta cuelgan de `idle` y se distinguen por silueta,
 * expresión y mirada, que son los ejes que el motor deja mover.
 */
export const INTERPRETACION: Record<FaceState, Interpretacion> = {
  // Los que bloub ya sabe decir.
  idle: suyo("idle"),
  thinking: suyo("thinking"),
  alert: suyo("alert"),
  waiting: suyo("notify"),
  pleased: suyo("wink"),
  offline: suyo("sleep"),
  arranque: suyo("wide"),
  working: suyo("orbit"),
  vibing: suyo("play"),
  launching: suyo("burst"),
  sending: suyo("comet"),

  // Atender es quedarse quieta: por eso la inquietud baja casi a cero.
  listening: { ...suyo("wide"), mirada: fija(0, -0.1, 0.05) },

  // El latido de hablar no va aquí: lo pone la escena con la cadencia real de
  // tokens, para que atascarse se vea como quietud y no como una animación.
  speaking: enReposo(null, "heureux"),

  // Las familias de herramienta.
  searching: enReposo(ESTIRADA, "curieux", barrido(2.8, 0.85)),
  browsing: enReposo(VENTANA, "curieux", renglones(2.4, 3)),
  reading: enReposo(HOJA, "attentif", renglones(3, 4)),
  rummaging: enReposo(null, "confus", fija(0, 0.7, 0.9)),
  // Deadpan de terminal: es la única cara que le pega a un `bash`.
  hacking: enReposo(VENTANA, "blase", fija(0, 0, 0.15)),
  writing: enReposo(null, "attentif", fija(-0.2, 0.6, 0.25)),
  noting: enReposo(null, "attentif", fija(-0.1, 0.45, 0.3)),
  peeking: enReposo(null, "curieux", fija(0, -0.75, 0.15)),
  handling: enReposo(null, "excite", fija(0.15, -0.6, 0.3)),
  reaching: enReposo(ESTIRADA, "surpris", fija(0.9, 0, 0.2)),
};

/** Qué le toca al motor para el estado dado. */
export const interpretar = (estado: FaceState): Interpretacion => INTERPRETACION[estado];
