/**
 * Cómo se mueve la mirada.
 *
 * Un ojo de verdad no deriva: hace **sacadas**. Salta en unas décimas de nada,
 * se queda fijo un rato mirando algo, y vuelve a saltar. La deriva suave que
 * había antes es justo lo que hacía que la cara pareciera una animación en
 * bucle en vez de alguien mirando cosas.
 *
 * Esto solo decide **adónde mirar y cuándo cambiar**. El salto en sí lo hace el
 * motor: `setLook` acepta una duración de transición, y pasarle 45 ms es
 * literalmente una sacada. Por eso `avanzar` devuelve `null` mientras no toca
 * moverse — llamar a `setLook` en cada fotograma reiniciaría la transición y el
 * ojo no llegaría nunca.
 */

export type Temperamento =
  /** Clavada en ti. Apenas se va, y vuelve enseguida. */
  | "pegada"
  /** Mira alrededor sin prisa. El reposo. */
  | "libre"
  /** Saltos amplios y seguidos: recorrer algo. */
  | "rapida"
  /** Disparada y corta: no encuentra lo que busca. */
  | "nerviosa"
  /** Muy de tarde en tarde. Cansancio, espera larga. */
  | "lenta"
  /** Se va hacia arriba, sin mirarte: pensar. */
  | "arriba"
  /** Renglón a renglón, con retorno de carro. Leer. */
  | "renglon";

export interface Objetivo {
  yaw: number;
  pitch: number;
}

interface Rasgos {
  /** Amplitud del salto en grados, [horizontal, vertical]. */
  amplitud: [number, number];
  /** Cuánto se queda fija, [mínimo, máximo] en segundos. */
  espera: [number, number];
  /** Probabilidad de volver al centro —a ti— en vez de irse a otro sitio. */
  vuelve: number;
  /** Desplazamiento fijo, para las miradas que tienen una querencia. */
  sesgo?: [number, number];
}

const RASGOS: Record<Temperamento, Rasgos> = {
  pegada: { amplitud: [3, 2], espera: [1.4, 2.6], vuelve: 1 },
  libre: { amplitud: [16, 10], espera: [0.7, 1.9], vuelve: 0.3 },
  rapida: { amplitud: [26, 7], espera: [0.14, 0.34], vuelve: 0 },
  nerviosa: { amplitud: [13, 13], espera: [0.08, 0.2], vuelve: 0 },
  lenta: { amplitud: [8, 6], espera: [2.2, 4], vuelve: 0.5 },
  arriba: { amplitud: [14, 5], espera: [0.9, 2.1], vuelve: 0, sesgo: [0, -11] },
  renglon: { amplitud: [0, 0], espera: [0.42, 0.42], vuelve: 0 },
};

/** Cuánto dura el salto. Cuarenta y cinco milisegundos es lo que tarda un ojo humano. */
export const DURACION_SACADA = 0.045;

export interface Sacadas {
  /**
   * Avanza el reloj y devuelve un objetivo NUEVO, o `null` si toca seguir quieta.
   *
   * `azar` se inyecta para poder probarlo: una mirada aleatoria no se puede
   * verificar, y una con la moneda trucada sí.
   */
  avanzar(temperamento: Temperamento, dt: number): Objetivo | null;
  /** Al cambiar de gesto: fuerza un salto en el fotograma siguiente. */
  reiniciar(): void;
}

export function crearSacadas(azar: () => number = Math.random): Sacadas {
  let espera = 0;
  let renglon = 0;

  return {
    reiniciar() {
      espera = 0;
      renglon = 0;
    },

    avanzar(temperamento, dt) {
      const paso = Number.isFinite(dt) ? Math.min(Math.max(dt, 0), 0.1) : 0;
      espera -= paso;
      if (espera > 0) return null;

      const r = RASGOS[temperamento] ?? RASGOS.libre;
      espera = r.espera[0] + azar() * (r.espera[1] - r.espera[0]);

      if (temperamento === "renglon") {
        // Cinco saltos hacia la derecha, uno al final del renglón y el retorno
        // de carro. Es la única mirada con memoria, y por eso va aparte.
        renglon = (renglon + 1) % 7;
        if (renglon === 6) return { yaw: -16, pitch: 6 };
        if (renglon === 5) return { yaw: 20, pitch: 0 };
        return { yaw: -14 + renglon * 7, pitch: 0 };
      }

      if (azar() < r.vuelve) return { yaw: 0, pitch: 0 };
      const sx = r.sesgo ? r.sesgo[0] : 0;
      const sy = r.sesgo ? r.sesgo[1] : 0;
      return {
        yaw: (azar() * 2 - 1) * r.amplitud[0] + sx,
        pitch: (azar() * 2 - 1) * r.amplitud[1] + sy,
      };
    },
  };
}
