import type { FaceState } from "../estados";
import type { Temperamento } from "../sacadas";
import type { FormaOjo } from "./formas";

/**
 * De lo que Vibi está haciendo a cómo se le pone la cara.
 *
 * El rediseño trae **ocho caras** y el catálogo tiene **treinta y dos estados**,
 * así que la pregunta no es cuál de las ocho toca sino qué separa a las cinco
 * que comparten una. La respuesta es el `porte`: la misma cara de ejecutar late
 * despacio en el terminal y a saltos al lanzar una aplicación, y el fuego arde
 * distinto en cada una. Son cinco números por estado, no cinco dibujos.
 *
 * Es el mismo reparto que en la cara anterior —quince siluetas convertidas en
 * quince puntos de un plano— aplicado a un personaje que sí tiene rasgos fijos.
 */

/** Lo que se le cuelga al personaje por fuera de la cara. */
export type Complemento = "ninguno" | "interrogacion" | "onda" | "lupa";

export interface Porte {
  /** El vaivén de fondo: [hercios, unidades de recorrido]. */
  vaiven: [number, number];
  /** Grados que se ladea la cabeza y se queda. Positivo, hacia su derecha. */
  ladeo: number;
  /** 0 a 1: cuánto tiembla. El recelo y el fallo son los únicos que lo usan fuerte. */
  tension: number;
  /** 0 a 1: cuánto arde el fuego cuando no pasa nada. Las señales vivas lo suben encima. */
  ardor: number;
  /** 0 a 1: el rebote de alegrarse. */
  brinco: number;
  /**
   * Rigidez del muelle del sombrero.
   *
   * Es lo que da el movimiento secundario: la chistera no se anima, **persigue**
   * a la cabeza con retraso. Bajo colea como si pesara; alto va tieso, que es lo
   * que le pega a recelar o a estar en un terminal.
   */
  garbo: number;
}

export interface Gesto {
  ojo: FormaOjo;
  /** El derecho, si el gesto los quiere distintos. Recelar y el `->` lo son. */
  ojoDer?: FormaOjo;
  /** Si enseña la boca. Solo la enseña trabajando. */
  boca: boolean;
  complemento: Complemento;
  sacada: Temperamento;
  porte: Partial<Porte>;
}

/** El porte de fondo. Lo que un gesto no diga se queda así. */
export const REPOSO: Porte = {
  vaiven: [0.24, 7],
  ladeo: 0,
  tension: 0,
  ardor: 0.15,
  brinco: 0,
  garbo: 120,
};

/** Las cinco de ejecutar comparten los ojos; las separa el porte. */
const prompt = (porte: Partial<Porte>, sacada: Temperamento): Gesto => ({
  ojo: "guion",
  ojoDer: "punta",
  boca: false,
  complemento: "ninguno",
  sacada,
  porte,
});

/** Las cinco de buscar comparten la lupa. */
const husmea = (
  ojo: FormaOjo,
  sacada: Temperamento,
  porte: Partial<Porte>,
): Gesto => ({ ojo, boca: false, complemento: "lupa", sacada, porte });

export const GESTOS: Record<FaceState, Gesto> = {
  // ------------------------------------------------------------------ contigo
  idle: { ojo: "pildora", boca: false, complemento: "ninguno", sacada: "libre", porte: {} },
  listening: {
    // Los ojos abiertos y clavados en ti, y la onda enseñando lo que te oye: es
    // el mismo dato que ya mide la captura de voz y que hasta ahora se tiraba.
    ojo: "pildora", boca: false, complemento: "onda", sacada: "pegada",
    porte: { vaiven: [0.34, 5], ardor: 0.2 },
  },
  speaking: {
    ojo: "sosiego", boca: false, complemento: "onda", sacada: "pegada",
    porte: { vaiven: [1.1, 5], ardor: 0.45, garbo: 100 },
  },
  thinking: {
    ojo: "redondo", boca: false, complemento: "interrogacion", sacada: "arriba",
    porte: { vaiven: [0.3, 5], ladeo: 7, ardor: 0.2 },
  },

  // --------------------------------------------------------------- arrancando
  arranque: {
    ojo: "redondo", boca: false, complemento: "interrogacion", sacada: "nerviosa",
    porte: { vaiven: [1.2, 6], ardor: 0.5, garbo: 80 },
  },
  vinculando: {
    ojo: "redondo", boca: false, complemento: "interrogacion", sacada: "lenta",
    porte: { ladeo: 6, ardor: 0.15, garbo: 95 },
  },

  // --------------------------------------------------------------- trabajando
  working: {
    ojo: "pildora", boca: true, complemento: "ninguno", sacada: "libre",
    porte: { vaiven: [0.62, 5], ardor: 0.35 },
  },
  writing: {
    ojo: "pildora", boca: true, complemento: "ninguno", sacada: "renglon",
    porte: { vaiven: [0.9, 4], ardor: 0.3 },
  },
  noting: {
    ojo: "pildora", boca: true, complemento: "ninguno", sacada: "lenta",
    porte: { vaiven: [0.45, 4], ardor: 0.25 },
  },
  trastienda: {
    // Trabaja donde no la ves, así que es la única de trabajar que no reclama
    // nada: se recoge, el fuego baja y la mirada va lenta.
    ojo: "rendija", boca: true, complemento: "ninguno", sacada: "lenta",
    porte: { vaiven: [0.3, 3], ladeo: -3, ardor: 0.12, garbo: 150 },
  },
  vibing: {
    ojo: "alegre", boca: true, complemento: "ninguno", sacada: "libre",
    porte: { vaiven: [1.4, 7], brinco: 0.35, ardor: 0.6, garbo: 85 },
  },

  // ---------------------------------------------------- ejecutando: el `->`
  hacking: prompt({ vaiven: [0.5, 3], ardor: 0.55, garbo: 200 }, "lenta"),
  launching: prompt({ vaiven: [1.5, 8], ardor: 0.8, garbo: 90 }, "rapida"),
  sending: prompt({ vaiven: [1.2, 7], ardor: 0.6, garbo: 100 }, "rapida"),
  reaching: prompt({ vaiven: [0.7, 6], ladeo: -6, ardor: 0.45, garbo: 95 }, "libre"),
  handling: prompt({ vaiven: [1.7, 6], ardor: 0.5, tension: 0.15 }, "rapida"),

  // ------------------------------------------------------ buscando: la lupa
  searching: husmea("pildora", "nerviosa", { vaiven: [0.8, 6], ardor: 0.4 }),
  browsing: husmea("pildora", "rapida", { vaiven: [0.9, 6], ardor: 0.35 }),
  rummaging: husmea("pildora", "nerviosa", { vaiven: [1.1, 5], ardor: 0.3, tension: 0.1 }),
  peeking: husmea("redondo", "rapida", { ladeo: -5, ardor: 0.25 }),
  reading: husmea("pildora", "renglon", { vaiven: [0.5, 4], ardor: 0.2 }),

  // --------------------------------------------------------------- esperando
  waiting: {
    ojo: "redondo", boca: false, complemento: "interrogacion", sacada: "pegada",
    porte: { vaiven: [0.4, 4], ladeo: 4, ardor: 0.1, garbo: 160 },
  },
  vigilando: {
    // Una vigilancia dura horas: mirar algo inquieto toda la tarde cansa, y por
    // eso esta es la más quieta de todas.
    ojo: "rendija", boca: false, complemento: "ninguno", sacada: "lenta",
    porte: { vaiven: [0.12, 4], ardor: 0.05, garbo: 140 },
  },

  // ---------------------------------------------------------- malas noticias
  recelo: {
    ojo: "furia", ojoDer: "furiaDer", boca: false, complemento: "ninguno", sacada: "pegada",
    porte: { vaiven: [0.5, 3], tension: 0.5, ardor: 0.5, garbo: 190 },
  },
  alert: {
    ojo: "redondo", boca: false, complemento: "ninguno", sacada: "nerviosa",
    porte: { vaiven: [1.6, 5], tension: 0.35, ardor: 0.6, garbo: 170 },
  },
  fallo: {
    ojo: "furia", ojoDer: "furiaDer", boca: false, complemento: "ninguno", sacada: "nerviosa",
    porte: { vaiven: [2.1, 4], tension: 0.9, ardor: 1, garbo: 210 },
  },
  perdida: {
    ojo: "redondo", boca: false, complemento: "ninguno", sacada: "nerviosa",
    porte: { vaiven: [0.3, 3], ladeo: 5, tension: 0.55, ardor: 0.2, garbo: 70 },
  },
  denegada: {
    ojo: "sosiego", boca: false, complemento: "ninguno", sacada: "lenta",
    porte: { vaiven: [0.2, 5], ladeo: 6, ardor: 0.05, garbo: 80 },
  },

  // --------------------------------------------------------- buenas noticias
  pleased: {
    ojo: "alegre", boca: false, complemento: "ninguno", sacada: "libre",
    porte: { brinco: 0.55, ardor: 0.5, garbo: 95 },
  },
  logro: {
    ojo: "alegre", boca: false, complemento: "ninguno", sacada: "arriba",
    porte: { brinco: 1, ardor: 0.85, garbo: 90 },
  },

  // ----------------------------------------------------------------- sistema
  cambiando: {
    ojo: "pildora", boca: false, complemento: "ninguno", sacada: "rapida",
    porte: { vaiven: [0.9, 10], ardor: 0.4, garbo: 85 },
  },
  offline: {
    // El fuego casi apagado es lo que separa dormirse de estar quieta: sin
    // canal no hay nada ardiendo.
    ojo: "rendija", boca: false, complemento: "ninguno", sacada: "lenta",
    porte: { vaiven: [0.1, 4], ladeo: 4, ardor: 0, garbo: 70 },
  },
};

/** El gesto de un estado, con el porte ya completo. */
export function gestoDe(estado: FaceState): Gesto & { porte: Porte } {
  const gesto = GESTOS[estado] ?? GESTOS.idle;
  return { ...gesto, porte: { ...REPOSO, ...gesto.porte } };
}
