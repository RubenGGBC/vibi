import { acotar } from "../faceMotion";

/**
 * Las señales vivas que se montan encima del gesto.
 *
 * Un gesto dice **qué** está haciendo Vibi. Esto dice **cómo le está yendo**, y
 * es lo que evita que hagan falta doscientas poses: en vez de un gesto para
 * «navegando por el paso 8 con el canal renqueando», hay un gesto de navegar y
 * unas señales encima.
 *
 * Las seis llegan hoy al frontend y se tiran a la basura. `boundaries` cuenta
 * los pasos encadenados del turno, los `delta` traen el caudal real de tokens,
 * el `pong` es el pulso del canal, y `nodo_presencia` dice qué equipo está
 * ejecutando. Ninguna necesita tocar el servidor.
 */

/** A partir de aquí un turno ya es largo; más pasos no cambian la lectura. */
export const MAX_PASOS = 12;

/** Deltas por segundo que se consideran «hablando a toda velocidad». */
export const MAX_CADENCIA = 40;

/** Retraso del pong, en ms, con el que la bola llega apagada del todo. */
export const MAX_RETRASO = 6000;

/** Más permisos que esto y los puntos dejarían de contarse de un vistazo. */
export const MAX_PENDIENTES = 5;

/** Cuánto dura el impulso del corte hacia una herramienta, en ms. */
export const DURACION_IMPULSO = 450;

export interface Senales {
  /** `ChatRuntimeState.boundaries`: pasos que lleva encadenados el turno. */
  pasos: number;
  /** Deltas por segundo sobre una ventana móvil. */
  cadencia: number;
  /** Milisegundos desde el último `pong`. */
  retrasoCanal: number;
  /** Nombre del equipo que ejecuta, o `null` si es este. */
  remoto: string | null;
  /** Órdenes esperando permiso. */
  pendientes: number;
  /** Marca de tiempo del último `boundary`. */
  corte: number;
}

export const SENALES_QUIETAS: Senales = {
  pasos: 0,
  cadencia: 0,
  retrasoCanal: 0,
  remoto: null,
  pendientes: 0,
  corte: 0,
};

export interface Ajustes {
  /** Multiplica el radio de la bola. 1 en reposo. */
  cargaBola: number;
  /** Frecuencia del latido de la bola, en hercios. */
  latidoBola: number;
  /** Brillo de la bola, de 1 a 0. Baja cuando el canal se arrastra. */
  brilloBola: number;
  /** Fuerza del latido del cuerpo al hablar, de 0 a 1. */
  pulsoHabla: number;
  /** Grados que se inclina el cuerpo por trabajar en otro equipo. */
  inclinacionRemota: number;
  /** Cuántos puntos orbitan por permisos pendientes. */
  puntosPendientes: number;
  /** Lo que queda del impulso del último corte, de 1 a 0. */
  impulsoCorte: number;
}

/** Hacia dónde se inclina cuando el trabajo pasa fuera. Siempre el mismo lado. */
const INCLINACION_REMOTA = 9;

/**
 * Traduce las señales a los números que las poses van a usar.
 *
 * Todo satura. Un turno de cuarenta pasos y uno de doce se leen igual —largo—,
 * y dejar que la bola siguiera creciendo solo serviría para que la cara se
 * saliera de la ventana.
 */
export function ajustesDe(senales: Senales, ahora: number): Ajustes {
  const lastre = acotar(senales.pasos, 0, MAX_PASOS) / MAX_PASOS;
  const retraso = acotar(senales.retrasoCanal, 0, MAX_RETRASO) / MAX_RETRASO;
  const desdeElCorte = ahora - senales.corte;

  return {
    cargaBola: 1 + lastre * 0.4,
    // Los pasos lo aceleran y el canal renqueante lo frena. Cuando las dos
    // señales tiran a la vez, gana el canal: no saber si sigue viva importa más
    // que saber cuánto lleva trabajando.
    latidoBola: (1.2 + lastre * 1.4) * (1 - retraso * 0.72),
    brilloBola: 1 - retraso,
    pulsoHabla: acotar(senales.cadencia, 0, MAX_CADENCIA) / MAX_CADENCIA,
    inclinacionRemota: senales.remoto ? INCLINACION_REMOTA : 0,
    puntosPendientes: Math.min(Math.max(Math.floor(senales.pendientes), 0), MAX_PENDIENTES),
    // Un corte con marca futura —los relojes no van sincronizados— cuenta como
    // recién ocurrido en vez de dar un impulso mayor que uno.
    impulsoCorte:
      senales.corte <= 0 ? 0 : acotar(1 - desdeElCorte / DURACION_IMPULSO, 0, 1),
  };
}
