import type { ExpressionId } from "./bloub/expressions";
import type { StateId } from "./bloub/states";
import type { FaceState } from "./estados";
import { REPOSO, type AjustesCuerpo } from "./liquido";
import type { FormaOjo } from "./ojos";
import type { Temperamento } from "./sacadas";

/**
 * De lo que Vibi está haciendo a lo que hay que dibujar.
 *
 * **Aquí no se inventa ni una medida.** Esa fue la lección cara: la primera
 * versión de esta cara la dibujé a ojo y los ojos salieron tres veces y media
 * más anchos de lo que toca, mirando de frente en vez de con el escorzo que les
 * da carácter. Lo que se conserva de bloub es exactamente eso: **dónde se posan
 * los ojos sobre la esfera y con qué escorzo**, que es lo que da volumen.
 *
 * Lo que ya no se conserva es su catálogo de animaciones ni la forma de sus
 * ojos, y por un motivo concreto: el cuerpo dejó de estar dibujado. Con una
 * masa que se calcula, una animación grabada de otro personaje la congela, y
 * una cápsula fija desperdicia el único canal que queda libre.
 *
 * Así que un gesto son ahora cuatro cosas:
 *
 * - **la forma de cada ojo** — píldora, rendija, arco, aspa…;
 * - **el temperamento de la mirada** — cómo salta, no dónde está;
 * - **las palancas del cuerpo** — cohesión, lóbulos, elongación, deriva;
 * - **y la expresión**, que es lo que sigue poniendo la orientación de la
 *   cabeza y la separación de los ojos, medidas sobre el vídeo.
 */

export interface Interpretacion {
  /**
   * El estado del catálogo de bloub.
   *
   * Es `idle` en todos, y no es pereza: es el único que el motor declara con
   * cuerpo Y cara reemplazables, así que es el único sobre el que el cuerpo
   * líquido y la expresión mandan los dos. Los demás traen su propia silueta
   * dibujada, que con una masa que fluye la congelaría.
   */
  base: StateId;
  /** Cuál de las expresiones medidas: pone la orientación de la cabeza y la separación. */
  expresion: ExpressionId | null;
  /** La forma del agujero del ojo interior. */
  ojo: FormaOjo;
  /** La del exterior, si el gesto los quiere distintos. Recelar es uno de cada. */
  ojoDer?: FormaOjo;
  /** Cómo salta la mirada. */
  sacada: Temperamento;
  /** Las palancas del cuerpo. Lo que no se diga se queda como en reposo. */
  cuerpo: Partial<AjustesCuerpo>;
}

/** Deriva como vector, que es como la mezcla el líquido: en ángulo daría media vuelta por el camino largo. */
const hacia = (grados: number, fuerza: number): [number, number] => [
  Math.cos((grados * Math.PI) / 180) * fuerza,
  Math.sin((grados * Math.PI) / 180) * fuerza,
];

/**
 * Las quince caras de trabajar comparten cuerpo y se separan por **hacia dónde
 * derivan y cuánto se agitan**. Eran quince siluetas y quince miradas escritas
 * a mano; ahora son quince puntos en el mismo plano.
 */
const trabajando = (
  extra: Partial<AjustesCuerpo>,
): Partial<AjustesCuerpo> => ({ cohesion: 0.62, agitacion: 1.3, suavidad: 0.6, ...extra });

export const INTERPRETACION: Record<FaceState, Interpretacion> = {
  // ---------------------------------------------------------------- contigo
  idle: {
    base: "idle", expresion: "neutre", ojo: "pildora", sacada: "libre",
    cuerpo: {},
  },
  listening: {
    // Los ojos se estiran a lo alto y se te quedan pegados: apenas saltan.
    base: "idle", expresion: "attentif", ojo: "alto", sacada: "pegada",
    cuerpo: { cohesion: 0.78, agitacion: 0.35, suavidad: 0.5, onda: [3, 0.03] },
  },
  thinking: {
    // Se concentra —la masa se aprieta y se pone tersa— y una gota se desprende
    // a dar vueltas por fuera. Antes eran tres puntos pulsando: el indicador de
    // «escribiendo…» de cualquier chat, y encima rígido.
    base: "idle", expresion: "somnolent", ojo: "finito", sacada: "arriba",
    cuerpo: { cohesion: 0.93, agitacion: 0.16, suavidad: 0.92, suelta: 1, latido: [0.4, 0.02], onda: [0, 0] },
  },
  speaking: {
    // El relieve lo pone la cadencia real de tokens, desde la escena.
    base: "idle", expresion: "heureux", ojo: "contento", sacada: "pegada",
    cuerpo: { cohesion: 0.7, agitacion: 0.85, suavidad: 0.55, lobulos: [4, 0.05], latido: [2.4, 0.05] },
  },

  // ------------------------------------------------------------- arrancando
  arranque: {
    // Grumosa y dispersa, alisándose mientras se reúne. Despertar deja de ser
    // una animación aparte: es el cuerpo formándose.
    base: "idle", expresion: "surpris", ojo: "redondo", sacada: "nerviosa",
    cuerpo: { cohesion: 0.3, agitacion: 1.5, suavidad: 0.16, gota: 0.7, onda: [4, 0.06], latido: [1.4, 0.07] },
  },
  vinculando: {
    base: "idle", expresion: "timide", ojo: "finito", sacada: "lenta",
    cuerpo: { cohesion: 0.5, agitacion: 0.6, suavidad: 0.4, gota: 0.86, latido: [0.9, 0.04] },
  },

  // ------------------------------------------------------------- trabajando
  working: {
    base: "idle", expresion: "attentif", ojo: "abierto", sacada: "libre",
    cuerpo: trabajando({}),
  },
  searching: {
    base: "idle", expresion: "curieux", ojo: "finito", sacada: "nerviosa",
    cuerpo: trabajando({ cohesion: 0.48, agitacion: 1.8, suavidad: 0.34, gota: 0.84,
      elongacion: [1.5, 0.78], lobulos: [3, 0.06], onda: [3, 0.07], deriva: hacia(180, 0.14) }),
  },
  browsing: {
    base: "idle", expresion: "curieux", ojo: "abierto", sacada: "rapida",
    cuerpo: trabajando({ cohesion: 0.58, agitacion: 1.4, elongacion: [1.42, 0.72], onda: [2, 0.05], deriva: hacia(9, 0.16) }),
  },
  rummaging: {
    base: "idle", expresion: "confus", ojo: "finito", sacada: "nerviosa",
    cuerpo: trabajando({ cohesion: 0.5, agitacion: 1.5, suavidad: 0.3, gota: 0.82, deriva: hacia(72, 0.2) }),
  },
  reading: {
    // Estrecha y muy alta, con la mirada bajando renglón a renglón.
    base: "idle", expresion: "attentif", ojo: "alto", sacada: "renglon",
    cuerpo: trabajando({ cohesion: 0.74, agitacion: 0.6, suavidad: 0.8, elongacion: [0.66, 1.4], deriva: hacia(86, 0.16) }),
  },
  writing: {
    base: "idle", expresion: "attentif", ojo: "finito", sacada: "renglon",
    cuerpo: trabajando({ cohesion: 0.76, agitacion: 0.8, suavidad: 0.72, elongacion: [0.86, 1.16], deriva: hacia(110, 0.16) }),
  },
  noting: {
    base: "idle", expresion: "attentif", ojo: "finito", sacada: "lenta",
    cuerpo: trabajando({ cohesion: 0.8, agitacion: 0.55, suavidad: 0.78, deriva: hacia(125, 0.13) }),
  },
  hacking: {
    // Lisa, tensa y aplastada, con dos rendijas mirando de lado y un latido
    // rápido y minúsculo: un cursor. Es la única cara que le pega a un bash.
    base: "idle", expresion: "blase", ojo: "rendija", sacada: "lenta",
    cuerpo: trabajando({ cohesion: 0.9, agitacion: 0.28, suavidad: 0.98, gota: 1.04,
      elongacion: [1.32, 0.74], latido: [3.8, 0.02], onda: [0, 0] }),
  },
  peeking: {
    base: "idle", expresion: "curieux", ojo: "abierto", sacada: "rapida",
    cuerpo: trabajando({ agitacion: 0.9, deriva: hacia(-70, 0.16) }),
  },
  handling: {
    base: "idle", expresion: "excite", ojo: "abierto", sacada: "rapida",
    cuerpo: trabajando({ agitacion: 1.6, suavidad: 0.5, deriva: hacia(-100, 0.2), onda: [3, 0.05] }),
  },
  launching: {
    base: "idle", expresion: "surpris", ojo: "redondo", sacada: "rapida",
    cuerpo: trabajando({ cohesion: 0.5, agitacion: 1.7, suavidad: 0.3, gota: 0.86, onda: [4, 0.07] }),
  },
  sending: {
    base: "idle", expresion: "surpris", ojo: "abierto", sacada: "rapida",
    cuerpo: trabajando({ agitacion: 1.5, suavidad: 0.45, deriva: hacia(28, 0.28), elongacion: [1.24, 0.88] }),
  },
  reaching: {
    // La masa entera se descuelga hacia un lado, estirándose fuera del marco.
    // Sustituye a los nueve grados de inclinación, que no los descifraba nadie.
    base: "idle", expresion: "surpris", ojo: "abierto", sacada: "libre",
    cuerpo: trabajando({ cohesion: 0.66, agitacion: 1.2, suavidad: 0.48, deriva: hacia(200, 0.34), elongacion: [1.2, 0.92] }),
  },
  vibing: {
    base: "idle", expresion: "excite", ojo: "contento", sacada: "libre",
    cuerpo: trabajando({ cohesion: 0.58, agitacion: 1.1, suavidad: 0.42, gota: 0.95,
      lobulos: [5, 0.08], onda: [5, 0.05], latido: [1.9, 0.11] }),
  },
  trastienda: {
    // Se recoge en un huevo liso y sellado. Es la única cara de trabajar que no
    // reclama atención, porque trabaja donde no la ves.
    base: "idle", expresion: "attentif", ojo: "finito", sacada: "lenta",
    cuerpo: trabajando({ cohesion: 0.98, agitacion: 0.24, suavidad: 1, gota: 1.08,
      elongacion: [0.72, 1.32], latido: [0.5, 0.02], onda: [0, 0] }),
  },
  forjando: {
    // Compacta y golpeando: el latido va a 1,28 Hz, el mismo compás que el
    // martillo de la otra cara, y se aplasta en cada golpe. Es lo único que
    // tiene este cuerpo para contar un martillazo, porque no empuña nada.
    base: "idle", expresion: "attentif", ojo: "finito", sacada: "lenta",
    cuerpo: trabajando({ cohesion: 0.86, agitacion: 0.55, suavidad: 0.66,
      elongacion: [1.06, 0.94], latido: [1.28, 0.17], onda: [3, 0.04] }),
  },

  // ------------------------------------------------------------ esperándote
  waiting: {
    // Quieta, tersa y apretada, con los ojos muy abiertos y clavados en ti. No
    // es una animación llamativa: es la postura de quien ha parado y espera.
    base: "idle", expresion: "attentif", ojo: "redondo", sacada: "pegada",
    cuerpo: { cohesion: 1, agitacion: 0.08, suavidad: 0.94, latido: [1.9, 0.06], onda: [0, 0] },
  },
  recelo: {
    // Un ojo abierto y el otro convertido en rendija. El servidor ya marca el
    // riesgo de cada orden: un `ls` y un `rm -rf` no merecen la misma cara.
    base: "idle", expresion: "mefiant", ojo: "redondo", ojoDer: "rendija", sacada: "pegada",
    cuerpo: { cohesion: 1, agitacion: 0.08, suavidad: 0.9, lobulos: [5, 0.03], latido: [2.6, 0.055], onda: [0, 0] },
  },
  vigilando: {
    // Los párpados casi cerrados. Una vigilancia dura horas: mirar algo inquieto
    // toda la tarde cansa, y por eso esta es la más quieta de todas.
    base: "idle", expresion: "somnolent", ojo: "dormido", sacada: "lenta",
    cuerpo: { cohesion: 0.82, agitacion: 0.05, suavidad: 0.84, latido: [0.22, 0.015], onda: [0, 0] },
  },
  denegada: {
    base: "idle", expresion: "triste", ojo: "triston", sacada: "lenta",
    cuerpo: { cohesion: 0.6, agitacion: 0.26, suavidad: 0.4, gota: 0.92,
      elongacion: [1, 0.9], deriva: hacia(86, 0.24), latido: [0.5, 0.03] },
  },

  // --------------------------------------------------------------- noticias
  alert: {
    base: "idle", expresion: "surpris", ojo: "redondo", sacada: "nerviosa",
    cuerpo: { cohesion: 0.86, agitacion: 0.7, suavidad: 0.7, latido: [3.2, 0.05] },
  },
  fallo: {
    // La masa se rompe en pedazos y los ojos se convierten en dos aspas. Es un
    // sobresalto, no un icono, y ya no comparte cara con «algo va mal».
    base: "idle", expresion: "surpris", ojo: "aspa", sacada: "nerviosa",
    cuerpo: { cohesion: 0.46, agitacion: 1.2, suavidad: 0.16, gota: 0.78, suelta: 3,
      onda: [4, 0.08], latido: [1.2, 0.06] },
  },
  pleased: {
    base: "idle", expresion: "heureux", ojo: "contento", sacada: "libre",
    cuerpo: { cohesion: 0.7, agitacion: 0.7, suavidad: 0.6, latido: [1.6, 0.07] },
  },
  logro: {
    base: "idle", expresion: "fier", ojo: "contento", sacada: "arriba",
    cuerpo: { cohesion: 0.64, agitacion: 0.55, suavidad: 0.64, lobulos: [3, 0.06], onda: [3, 0.04], latido: [0.9, 0.1] },
  },
  perdida: {
    // Ojos muy abiertos y temblando, con una gota suelta que no vuelve. No es
    // dormirse: es quedarse sin saber en qué quedó lo que estaba haciendo.
    base: "idle", expresion: "effraye", ojo: "redondo", sacada: "nerviosa",
    cuerpo: { cohesion: 0.52, agitacion: 0.14, suavidad: 0.32, gota: 0.88, suelta: 1,
      deriva: hacia(86, 0.32), onda: [3, 0.05], latido: [0.3, 0.02] },
  },

  // ---------------------------------------------------------------- sistema
  cambiando: {
    base: "idle", expresion: "excite", ojo: "abierto", sacada: "rapida",
    cuerpo: { cohesion: 0.36, agitacion: 1.8, suavidad: 0.3, gota: 0.8, onda: [5, 0.08], latido: [1.6, 0.07] },
  },
  offline: {
    base: "idle", expresion: "somnolent", ojo: "dormido", sacada: "lenta",
    cuerpo: { cohesion: 0.54, agitacion: 0.03, suavidad: 0.9, elongacion: [1.16, 0.82],
      deriva: hacia(86, 0.24), latido: [0.11, 0.012], onda: [0, 0] },
  },
};

/** Qué le toca al motor para el estado dado. */
export const interpretar = (estado: FaceState): Interpretacion => INTERPRETACION[estado];

/** Las palancas completas del gesto: lo que no diga se queda como en reposo. */
export function cuerpoDe(estado: FaceState): AjustesCuerpo {
  return { ...REPOSO, ...INTERPRETACION[estado].cuerpo };
}
