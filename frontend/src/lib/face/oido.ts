/**
 * Lo que Vibi oye.
 *
 * Es un asistente de voz y su cara nunca ha oído nada: mientras le hablas, la
 * silueta hace exactamente lo mismo que en reposo. Y lo llamativo es que **el
 * dato ya se estaba calculando y se tiraba**: `startVoiceCapture` mide el RMS
 * del micrófono en cada fotograma para saber cuándo te has callado, lo compara
 * con un umbral y descarta el número.
 *
 * Este módulo solo lo publica. No abre ningún `AudioContext` ni pide permisos
 * —de eso ya se encarga la captura— así que si nadie está grabando el nivel es
 * cero y la cara respira como siempre. Ese es el motivo de que sea una variable
 * suelta y no un contexto de React: lo lee el bucle de dibujo sesenta veces por
 * segundo, y pasar por el árbol de componentes para eso sería absurdo.
 */

/**
 * Por debajo de esto no es voz, es la habitación.
 *
 * Es el mismo umbral con el que `voice.ts` decide que te has callado. Va
 * repetido a propósito y no importado: son dos decisiones distintas que hoy
 * coinciden —cuándo cortar la grabación y cuándo mover la cara— y atarlas
 * obligaría a cambiar las dos cada vez que se afine una.
 */
const SUELO = 0.028;

/**
 * A partir de aquí ya estás hablando alto y la lectura no cambia.
 *
 * Medido a ojo sobre voz normal de escritorio: el RMS de hablar tranquilo a
 * medio metro se mueve entre 0,04 y 0,15. Dejar el techo en 0,22 da recorrido
 * para levantar la voz sin que la cara se sature en cuanto abres la boca.
 */
const TECHO = 0.22;

let nivel = 0;

/** Lo llama el monitor del micrófono con el RMS crudo de la ventana actual. */
export function publicarNivelDeVoz(rms: number): void {
  nivel = normalizarNivel(rms);
}

/** Cuánto se te oye ahora mismo, de 0 a 1. */
export function nivelDeVoz(): number {
  return nivel;
}

/**
 * Al soltar el micrófono.
 *
 * Sin esto la cara se queda erizada en la última sílaba para siempre: nadie
 * vuelve a publicar un cero porque el bucle que medía ya no existe.
 */
export function callarOido(): void {
  nivel = 0;
}

/** El mapeo, aparte para poder probarlo sin tocar el módulo entero. */
export function normalizarNivel(rms: number): number {
  if (!Number.isFinite(rms)) return 0;
  const bruto = (rms - SUELO) / (TECHO - SUELO);
  return Math.min(1, Math.max(0, bruto));
}
