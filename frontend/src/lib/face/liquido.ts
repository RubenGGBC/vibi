import { PROFILE_SAMPLES } from "./bloub/profiles";

/**
 * El cuerpo, calculado en vez de dibujado.
 *
 * El círculo de bloub es la única parte de la cara que **no** está medida sobre
 * el vídeo de referencia: un círculo es un círculo. Aquí se sustituye por seis
 * gotas y su unión, así que la forma sale de unos números y nunca es la misma
 * dos veces.
 *
 * La unión se calcula aquí y no con `unionOfCirclesProfile` de bloub porque
 * hace falta el radio de cada gota por separado —una que se desprende encoge
 * mientras sale— y aquella función toma el máximo y no deja meter mano. Es el
 * mismo lanzamiento de rayo, ángulo por ángulo.
 *
 * Cada gesto trae sus palancas y **el módulo las mezcla por dentro**: quien lo
 * usa pasa el objetivo y nunca el valor actual, que es lo que garantiza que
 * cambiar de gesto sea una transición y no un corte.
 */

/**
 * Las gotas, en unidades del radio de la bola en reposo.
 *
 * Seis y no más: con cuatro se sigue viendo el círculo debajo y con diez la
 * unión se vuelve una masa sin carácter. Las velocidades no son múltiplos unas
 * de otras a propósito — si lo fueran, el ciclo se repetiría a ojo cada pocos
 * segundos, que es lo que delata a un salvapantallas.
 *
 * La primera es el ancla: grande, en el centro y quieta. Es lo que garantiza
 * que la unión sea una sola pieza por mucho que las otras se separen.
 */
const GOTAS = [
  { d: 0.0, v: 0.0, f: 0.19, fase: 0.0, r: 0.8 },
  { d: 0.22, v: 0.31, f: 0.27, fase: 0.0, r: 0.68 },
  { d: 0.26, v: -0.24, f: 0.21, fase: 2.1, r: 0.64 },
  { d: 0.19, v: 0.39, f: 0.33, fase: 4.2, r: 0.66 },
  { d: 0.28, v: -0.18, f: 0.17, fase: 1.1, r: 0.62 },
  { d: 0.24, v: 0.45, f: 0.37, fase: 3.4, r: 0.63 },
] as const;

/** Cuánto se separan y se juntan las gotas de su órbita. */
const VAIVEN = 0.32;

/** Lo que crece el contorno con la voz a tope, en unidades de radio. */
const RELIEVE = 0.17;

/**
 * Muestras por segundo a las que avanza el eco de la voz.
 *
 * Va por tiempo y no por fotograma porque la cara dibuja a 24 en reposo y a 60
 * trabajando: atarlo al fotograma haría que la onda viajara al doble justo
 * cuando se pone a hacer cosas.
 */
const TASA_ECO = 26;

/** Sube casi de golpe y baja despacio, como un vúmetro. En segundos. */
const ATAQUE = 0.035;
const CAIDA = 0.28;

/** Lo que tarda el cuerpo en llegar a su forma nueva. Más largo que el ojo, a propósito. */
const MORFEO = 0.5;

/**
 * El radio medio al que se normaliza todo perfil, en unidades de bola.
 *
 * **Estirar cambia la forma, no el tamaño.** Sin esto, subir la elongación o
 * bajar la cohesión hacía crecer el cuerpo entero, y medido salía que
 * `browsing` llegaba a 2,14 radios — unos 380 px de ancho en una ventana de
 * 320, o sea recortado. Es además lo correcto en animación: al aplastar algo se
 * conserva el volumen.
 *
 * El valor es la media del perfil en reposo, así que en reposo no cambia nada.
 */
const MEDIA = 0.92;

export interface AjustesCuerpo {
  /** Cuánto se abrazan las gotas al centro. 1 es una bola tensa; 0 se desparrama. */
  cohesion: number;
  /** Multiplicador de la velocidad orbital. */
  agitacion: number;
  /** Cuánto se redondea el contorno. 0 deja los pliegues; 1 lo deja terso. */
  suavidad: number;
  /** [orden, amplitud] de los lóbulos que le salen y giran. */
  lobulos: [number, number];
  /** [orden, amplitud] de la onda que RECORRE la superficie. */
  onda: [number, number];
  /** Estirado [x, y]. Es lo que sustituye a las siluetas dibujadas. */
  elongacion: [number, number];
  /** Multiplicador del tamaño de cada gota. Pequeñas, más grumo. */
  gota: number;
  /** Cuántas gotas se desprenden y orbitan por fuera. */
  suelta: number;
  /** Hacia dónde se descuelga la masa, ya como vector [x, y]. */
  deriva: [number, number];
  /** [hercios, amplitud] del latido global. */
  latido: [number, number];
}

export const REPOSO: AjustesCuerpo = {
  cohesion: 0.72,
  agitacion: 0.5,
  suavidad: 0.7,
  lobulos: [0, 0],
  onda: [2, 0.02],
  elongacion: [1, 1],
  gota: 1,
  suelta: 0,
  deriva: [0, 0],
  latido: [0.62, 0.05],
};

/** Una gota que se ha desprendido del cuerpo, en unidades de radio. */
export interface GotaSuelta {
  x: number;
  y: number;
  r: number;
  /** De 0 a 1 según va saliendo. Sirve para que aparezca sin dar un salto. */
  cuota: number;
}

export interface Liquido {
  /**
   * El perfil de este instante: 64 radios listos para `BotEngine.setShape`.
   *
   * `nivel` es cuánto se te oye (0 a 1), `dt` los segundos desde el último
   * fotograma y `objetivo` las palancas del gesto al que se va.
   */
  perfil(t: number, nivel: number, dt: number, objetivo?: AjustesCuerpo): number[];
  /** Las gotas desprendidas del último fotograma. */
  sueltas(): GotaSuelta[];
}

const lerp = (a: number, b: number, k: number) => a + (b - a) * k;

export function crearLiquido(): Liquido {
  // El eco: los niveles de voz recientes, para que la onda RECORRA el contorno
  // en vez de latir entero a la vez. Latir a la vez se lee como un corazón;
  // recorrer se lee como sonido, que es lo que es.
  const eco = new Float32Array(PROFILE_SAMPLES);
  let cabeza = 0;
  let resto = 0;
  let suave = 0;
  let fuera: GotaSuelta[] = [];

  // El estado MEZCLADO. Todo lo que se dibuja sale de aquí, nunca del objetivo.
  const m: AjustesCuerpo = {
    ...REPOSO,
    lobulos: [...REPOSO.lobulos] as [number, number],
    onda: [...REPOSO.onda] as [number, number],
    elongacion: [...REPOSO.elongacion] as [number, number],
    deriva: [...REPOSO.deriva] as [number, number],
    latido: [...REPOSO.latido] as [number, number],
  };

  return {
    sueltas: () => fuera,

    perfil(t, nivel, dt, objetivo = REPOSO) {
      const paso = Number.isFinite(dt) ? Math.min(Math.max(dt, 0), 0.1) : 0;
      const k = 1 - Math.exp(-paso / MORFEO);
      for (const p of ["cohesion", "agitacion", "suavidad", "gota", "suelta"] as const) {
        m[p] = lerp(m[p], objetivo[p], k);
      }
      for (const p of ["lobulos", "onda", "elongacion", "deriva", "latido"] as const) {
        m[p] = [lerp(m[p][0], objetivo[p][0], k), lerp(m[p][1], objetivo[p][1], k)];
      }

      const objVoz = Number.isFinite(nivel) ? Math.min(Math.max(nivel, 0), 1) : 0;
      // Ataque y caída distintos. Con la misma constante en los dos sentidos la
      // cara tiembla entre sílabas en vez de hablar.
      const tau = objVoz > suave ? ATAQUE : CAIDA;
      suave += (objVoz - suave) * (1 - Math.exp(-paso / tau));

      resto += paso * TASA_ECO;
      const avance = Math.min(Math.floor(resto), PROFILE_SAMPLES);
      resto -= avance;
      for (let n = 0; n < avance; n += 1) {
        cabeza = (cabeza + 1) % PROFILE_SAMPLES;
        eco[cabeza] = suave;
      }
      if (avance === 0) eco[cabeza] = Math.max(eco[cabeza], suave);

      const crudo = new Array<number>(PROFILE_SAMPLES).fill(0);
      const dispersion = (1 - m.cohesion) * 1.9;
      fuera = [];

      GOTAS.forEach((g, idx) => {
        // Una gota que se desprende no aparece de golpe: SALE. Viaja hacia
        // fuera y su radio encoge, así que no hay ningún fotograma en el que
        // surja un círculo donde antes no había nada.
        const cuota = Math.min(Math.max(m.suelta - (GOTAS.length - 1 - idx), 0), 1);
        const angulo = g.fase + t * g.v * (m.agitacion + 0.05) * 2;
        const d = g.d * (1 + Math.sin(t * g.f * 2.3 + g.fase) * VAIVEN) * (1 + dispersion) + cuota * 0.62;
        const cx = Math.cos(angulo) * d + m.deriva[0];
        // Aplastada un pelo en vertical: una gota que cuelga no es redonda.
        const cy = Math.sin(angulo) * d * 0.88 + m.deriva[1];
        const r = g.r * m.gota * (1 - cuota * 0.62);
        if (cuota > 0.02) fuera.push({ x: cx, y: cy, r: r * 0.9, cuota });
        if (cuota > 0.96) return;
        for (let i = 0; i < PROFILE_SAMPLES; i += 1) {
          const a = (i / PROFILE_SAMPLES) * Math.PI * 2;
          const dx = Math.cos(a);
          const dy = Math.sin(a);
          const b = dx * cx + dy * cy;
          const disc = b * b - (cx * cx + cy * cy - r * r);
          if (disc < 0) continue;
          const v = b + Math.sqrt(disc);
          if (v > crudo[i]) crudo[i] = v;
        }
      });

      // Suavidad: se mezcla el perfil crudo con uno alisado. A 0 se ven los
      // pliegues donde se juntan las gotas; a 1 es una superficie tersa.
      const liso = crudo.slice();
      for (let n = 0; n < 4; n += 1) {
        const c = liso.slice();
        for (let i = 0; i < PROFILE_SAMPLES; i += 1) {
          liso[i] = (c[(i - 1 + PROFILE_SAMPLES) % PROFILE_SAMPLES] + c[i] * 2 + c[(i + 1) % PROFILE_SAMPLES]) / 4;
        }
      }

      const respiro = 1 + Math.sin(t * m.latido[0] * Math.PI * 2) * m.latido[1];
      const salida = new Array<number>(PROFILE_SAMPLES);
      for (let i = 0; i < PROFILE_SAMPLES; i += 1) {
        const a = (i / PROFILE_SAMPLES) * Math.PI * 2;
        const mitad = Math.min(i, PROFILE_SAMPLES - i);
        let r = lerp(crudo[i], liso[i], Math.min(Math.max(m.suavidad, 0), 1));
        // La onda se lee simétrica desde arriba hacia los dos lados. Una cara
        // tiene eje; un osciloscopio no, y sin esto parece lo segundo.
        r += eco[(cabeza - mitad * 2 + PROFILE_SAMPLES * 2) % PROFILE_SAMPLES] * RELIEVE;
        r *= 1 + Math.sin(a * m.lobulos[0] + t * 0.8) * m.lobulos[1];
        // Una onda que RECORRE la superficie. Sin ella la silueta cambia entre
        // gestos pero dentro de cada uno solo respira, y eso se lee como quieta.
        r *= 1 + Math.sin(a * m.onda[0] - t * 1.35) * m.onda[1];
        r *= respiro;
        r *= Math.sqrt(
          Math.pow(Math.cos(a) * m.elongacion[0], 2) + Math.pow(Math.sin(a) * m.elongacion[1], 2),
        );
        salida[i] = r;
      }

      // Normalización: la media manda, y no el máximo. Con el máximo, una punta
      // de lóbulo encogería el cuerpo entero cada vez que pasara por delante.
      let suma = 0;
      for (let i = 0; i < PROFILE_SAMPLES; i += 1) suma += salida[i];
      const escala = suma > 0 ? (MEDIA * PROFILE_SAMPLES) / suma : 1;
      for (let i = 0; i < PROFILE_SAMPLES; i += 1) salida[i] *= escala;
      for (const g of fuera) { g.x *= escala; g.y *= escala; g.r *= escala; }

      return salida;
    },
  };
}
