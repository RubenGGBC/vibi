import type { Escena, Pregunta } from "./tipos";

export interface EstadoPregunta {
  acertada: boolean;
  fallos: number;
  resuelta: boolean;
  /** La pista que toca tras el último fallo, si queda alguna. */
  pista: string | null;
  /** Solo cuando ya está resuelta. */
  explicacion: string | null;
}

/**
 * Cómo va una pregunta. Misma regla que `estado_pregunta` en el servidor:
 * cada fallo destapa la pista siguiente; acertar, o fallar con las pistas ya
 * gastadas, la cierra y enseña la explicación.
 */
export function estadoPregunta(pregunta: Pregunta, elegidas: number[]): EstadoPregunta {
  const pistas = pregunta.pistas ?? [];
  const acertada = elegidas.includes(pregunta.correcta);
  const fallos = elegidas.filter((o) => o !== pregunta.correcta).length;
  const resuelta = acertada || fallos > pistas.length;
  return {
    acertada,
    fallos,
    resuelta,
    pista: fallos && !resuelta ? pistas[fallos - 1] : null,
    explicacion: resuelta ? pregunta.explicacion : null,
  };
}

export const elegidasEn = (escena: Escena, indice: number): number[] =>
  escena.progreso?.respuestas[String(indice + 1)] ?? [];

// Lo que el alumno le dice al tutor desde la escena. Empieza por
// «(Estudio, paso N)»: así lo reconoce el modelo (ver COMO_TUTOR).

const prefijo = (indice: number) => `(Estudio, paso ${indice + 1})`;

function deQueVa(escena: Escena, indice: number): string {
  const paso = escena.pasos[indice];
  const idea = paso.idea?.trim();
  if (idea) return idea;
  const texto = paso.texto.trim();
  return texto.length > 120 ? `${texto.slice(0, 117)}…` : texto;
}

export function mensajeNoLoEntiendo(escena: Escena, indice: number): string {
  return `${prefijo(indice)} No lo entiendo: «${deQueVa(escena, indice)}». ¿Me lo explicas de otra forma?`;
}

export function mensajeTrasFallar(escena: Escena, indice: number): string {
  const pregunta = escena.pasos[indice].pregunta;
  if (!pregunta) return mensajeNoLoEntiendo(escena, indice);
  const elegidas = elegidasEn(escena, indice).map((o) => `«${pregunta.opciones[o]}»`);
  return `${prefijo(indice)} En «${pregunta.enunciado}» elegí ${elegidas.join(" y luego ")} y no era. ¿Por qué?`;
}

export function mensajeAlTerminar(escena: Escena): string {
  return `${prefijo(escena.pasos.length - 1)} He llegado al final. ¿Repasamos?`;
}
