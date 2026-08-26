/**
 * La forma de los ojos.
 *
 * **Durante mucho tiempo di por sentado que la cápsula de bloub era
 * intocable**, con el argumento de que era «lo único medido». Es falso, y me
 * costó tres intentos verlo: lo medido es *dónde* se posan los ojos sobre la
 * esfera y *con qué escorzo* —eso es lo que les da volumen y sigue viniendo
 * entero del motor, matriz incluida—. Que además sean píldoras es una elección
 * de aquel personaje, y Vibi no tiene por qué heredarla.
 *
 * Así que el motor conserva la colocación y aquí se decide la silueta. En el
 * SVG eso es literalmente el atributo `d` del agujero: la matriz que lo coloca
 * no se toca.
 *
 * Todas las formas se muestrean con los MISMOS puntos y en el mismo sentido,
 * que es lo que permite pasar de una a otra interpolando punto a punto. Sin esa
 * regla, morfar un arco en un aspa daría un revoltijo.
 */

/** Puntos por contorno. Treinta y dos es suficiente para que una curva de dos tramos se lea redonda. */
const M = 32;

/** Los ojos van en unidades de viewBox, igual que el resto del motor: radio de la bola = 100. */
export type FormaOjo =
  /** La de bloub, medida sobre el vídeo. El punto de partida. */
  | "pildora"
  /** Grande y despierto. */
  | "abierto"
  /** Redondo del todo: sorpresa, susto, y mirarte fijo. */
  | "redondo"
  /** Rendija horizontal: la cara de póker del terminal. */
  | "rendija"
  /** Estrecho y corto: concentrarse, entornar. */
  | "finito"
  /** Estirado a lo alto: atender. */
  | "alto"
  /** Arco hacia arriba. La única forma que no se confunde con ninguna otra. */
  | "contento"
  /** Arco hacia abajo. */
  | "triston"
  /** Una línea: dormir, y quedarse sin servidor. */
  | "dormido"
  /** Un aspa. El error. */
  | "aspa";

interface Punto { x: number; y: number }

const TAU = Math.PI * 2;
const muestrear = (fn: (u: number) => Punto): Punto[] =>
  Array.from({ length: M }, (_, i) => fn(i / M));

const pot = (v: number, e: number) => Math.sign(v) * Math.pow(Math.abs(v), e);

/**
 * Superelipse. `n` a 2 es una elipse; subiéndolo se acerca a una píldora.
 *
 * Se usa para casi todas porque una sola familia con dos números da la mitad
 * del vocabulario, y morfa consigo misma sin sobresaltos.
 */
const supe = (w: number, h: number, n: number) =>
  muestrear((u) => {
    const a = u * TAU;
    return { x: (w / 2) * pot(Math.cos(a), 2 / n), y: (h / 2) * pot(Math.sin(a), 2 / n) };
  });

/**
 * Un arco grueso: la sonrisa de los ojos, y del revés la pena.
 *
 * La primera mitad del recorrido traza el borde de fuera y la segunda vuelve
 * por el de dentro, para que empiece y avance como las superelipses.
 */
const arco = (w: number, h: number, grosor: number, signo: number) =>
  muestrear((u) => {
    const ida = u < 0.5;
    const v = ida ? u * 2 : (1 - u) * 2;
    return {
      x: (v - 0.5) * w,
      y: Math.sin(v * Math.PI) * h * signo + (ida ? 0 : grosor),
    };
  });

/** Un aspa, recorrida como un solo contorno de doce vértices. */
const aspa = (w: number, g: number) => {
  const v: Array<[number, number]> = [
    [-w, -w + g], [-w + g, -w], [0, -g], [w - g, -w], [w, -w + g], [g, 0],
    [w, w - g], [w - g, w], [0, g], [-w + g, w], [-w, w - g], [-g, 0],
  ];
  return muestrear((u) => {
    const s = u * v.length;
    const i = Math.floor(s) % v.length;
    const f = s - Math.floor(s);
    const a = v[i];
    const b = v[(i + 1) % v.length];
    return { x: a[0] + (b[0] - a[0]) * f, y: a[1] + (b[1] - a[1]) * f };
  });
};

const FORMAS: Record<FormaOjo, Punto[]> = {
  // 18,6 x 41,2: EYE_W y EYE_H de bloub, en unidades de viewBox.
  pildora: supe(18.6, 41.2, 6),
  abierto: supe(30, 44, 3.4),
  redondo: supe(38, 38, 2),
  rendija: supe(30, 9, 6),
  finito: supe(13, 30, 6),
  alto: supe(17, 50, 6),
  contento: arco(38, 15, 9, -1),
  triston: arco(36, 13, 9, 1),
  dormido: supe(32, 5, 6),
  aspa: aspa(17, 6),
};

/** El trazado de un contorno, con los puntos medios como anclas: sale suave sin calcular tangentes. */
function trazar(pts: Punto[]): string {
  let d = `M${((pts[M - 1].x + pts[0].x) / 2).toFixed(2)} ${((pts[M - 1].y + pts[0].y) / 2).toFixed(2)}`;
  for (let i = 0; i < M; i += 1) {
    const a = pts[i];
    const b = pts[(i + 1) % M];
    d += `Q${a.x.toFixed(2)} ${a.y.toFixed(2)} ${((a.x + b.x) / 2).toFixed(2)} ${((a.y + b.y) / 2).toFixed(2)}`;
  }
  return `${d}Z`;
}

export interface Ojos {
  /**
   * Avanza el morfeo y devuelve los dos trazados, interior y exterior.
   *
   * Se pasan las dos formas por separado porque hay gestos que las quieren
   * distintas: recelar es un ojo abierto y el otro convertido en rendija.
   */
  trazar(interior: FormaOjo, exterior: FormaOjo, dt: number): [string, string];
}

/** Lo que tarda un ojo en cambiar de forma. Corto: llega antes que el cuerpo, a propósito. */
const MORFEO = 0.18;

export function crearOjos(): Ojos {
  const vivo: [Punto[], Punto[]] = [
    FORMAS.pildora.map((p) => ({ ...p })),
    FORMAS.pildora.map((p) => ({ ...p })),
  ];

  return {
    trazar(interior, exterior, dt) {
      const paso = Number.isFinite(dt) ? Math.min(Math.max(dt, 0), 0.1) : 0;
      const k = 1 - Math.exp(-paso / MORFEO);
      const destino = [FORMAS[interior] ?? FORMAS.pildora, FORMAS[exterior] ?? FORMAS.pildora];
      for (let o = 0; o < 2; o += 1) {
        for (let i = 0; i < M; i += 1) {
          vivo[o][i].x += (destino[o][i].x - vivo[o][i].x) * k;
          vivo[o][i].y += (destino[o][i].y - vivo[o][i].y) * k;
        }
      }
      return [trazar(vivo[0]), trazar(vivo[1])];
    },
  };
}

/** Para los tests: cuántos puntos tiene cada contorno. */
export const PUNTOS_POR_OJO = M;
