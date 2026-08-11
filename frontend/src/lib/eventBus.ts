import type { ServerEvent } from "../types";

/**
 * El canal de eventos, en crudo.
 *
 * `useEvents` traduce cada evento a cambios en la caché de consultas, que es lo
 * que necesitan las pantallas: una lista de tareas, una cola de aprobaciones.
 * Pero hay cosas que solo existen en el instante en que pasan —ha llegado un
 * archivo, una tarea acaba de fallar— y no dejan huella que consultar después.
 * La cara del companion vive justo de eso, así que necesita el evento tal cual
 * llegó y no su poso en la caché.
 *
 * Este módulo no interpreta nada: reparte. Quién decide qué cara poner es
 * `faceMood`.
 */

type EventoHandler = (event: ServerEvent) => void;

const oyentes = new Set<EventoHandler>();

export function publicarEvento(event: ServerEvent): void {
  // Una copia de la lista: un oyente que se da de baja al recibir el evento no
  // debe romper el reparto a los que van detrás.
  for (const oyente of [...oyentes]) {
    try {
      oyente(event);
    } catch {
      // Un oyente roto no puede tumbar el canal ni a los demás.
    }
  }
}

export function suscribirEventos(handler: EventoHandler): () => void {
  oyentes.add(handler);
  return () => oyentes.delete(handler);
}

/**
 * En qué estado está el WebSocket.
 *
 * `caido` no es lo mismo que `conectando`: al arrancar todavía no se sabe si
 * hay servidor, y poner cara de desconectada antes del primer intento sería
 * mentir. Solo se cae después de haber estado conectada o de fallar el intento.
 */
export type EstadoCanal = "conectando" | "conectado" | "caido";

let canal: EstadoCanal = "conectando";
const oyentesCanal = new Set<(estado: EstadoCanal) => void>();

export function publicarEstadoCanal(estado: EstadoCanal): void {
  if (canal === estado) return;
  canal = estado;
  for (const oyente of [...oyentesCanal]) {
    try {
      oyente(estado);
    } catch {
      // Igual que arriba: el canal manda, los oyentes no lo tumban.
    }
  }
}

export function estadoCanalActual(): EstadoCanal {
  return canal;
}

export function suscribirCanal(
  handler: (estado: EstadoCanal) => void,
): () => void {
  oyentesCanal.add(handler);
  return () => oyentesCanal.delete(handler);
}
