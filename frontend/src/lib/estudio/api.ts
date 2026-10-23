import type { QueryClient } from "@tanstack/react-query";

import { apiFetch } from "../api";
import type { Escena, Objeto } from "./tipos";

export const escenaKey = ["estudio", "escena"] as const;

export const pedirEscena = (): Promise<Escena> => apiFetch<Escena>("/api/estudio/escena");

export const irAPaso = (indice: number): Promise<{ indice: number }> =>
  apiFetch("/api/estudio/paso", {
    method: "POST",
    body: JSON.stringify({ indice }),
  });

export const subirCaptura = (capturaId: string, imagen: Blob): Promise<unknown> =>
  apiFetch(`/api/estudio/capturas/${encodeURIComponent(capturaId)}`, {
    method: "POST",
    body: imagen,
    headers: { "Content-Type": "image/jpeg" },
  });

/** Lo que llega por el WebSocket. Solo se acepta una escena más nueva. */
export function aplicarEscena(client: QueryClient, escena: Escena): void {
  client.setQueryData<Escena>(escenaKey, (actual) =>
    actual && actual.version > escena.version ? actual : escena,
  );
}

export function aplicarPaso(client: QueryClient, indice: number): void {
  client.setQueryData<Escena>(escenaKey, (actual) => {
    if (!actual) return actual;
    const progreso = actual.progreso ?? { visto_hasta: 0, respuestas: {} };
    return {
      ...actual,
      paso_actual: indice,
      progreso: { ...progreso, visto_hasta: Math.max(progreso.visto_hasta, indice) },
    };
  });
}

export interface EstadoRespuesta {
  elegidas: number[];
}

/** El alumno contesta la pregunta de un paso; vuelve por el WebSocket a sus ventanas. */
export const responder = (indice: number, opcion: number): Promise<EstadoRespuesta> =>
  apiFetch("/api/estudio/respuesta", {
    method: "POST",
    body: JSON.stringify({ indice, opcion }),
  });

export function aplicarRespuesta(client: QueryClient, indice: number, elegidas: number[]): void {
  client.setQueryData<Escena>(escenaKey, (actual) => {
    if (!actual) return actual;
    const progreso = actual.progreso ?? { visto_hasta: 0, respuestas: {} };
    return {
      ...actual,
      progreso: { ...progreso, respuestas: { ...progreso.respuestas, [String(indice + 1)]: elegidas } },
    };
  });
}

export interface AjusteManual {
  parte?: string | null;
  posicion?: number[];
  rotacion?: number[];
  escala?: number[];
  restablecer?: boolean;
}

/** Lo que el alumno movió con el gizmo. La escena nueva vuelve por el WebSocket. */
export const ajustarObjeto = (objetoId: string, ajuste: AjusteManual): Promise<Objeto> =>
  apiFetch(`/api/estudio/objetos/${encodeURIComponent(objetoId)}/ajuste`, {
    method: "POST",
    body: JSON.stringify(ajuste),
  });

/** Lo movido se ve ya, sin esperar a que vuelva la escena del servidor. */
export function aplicarAjusteLocal(client: QueryClient, objetoId: string, ajuste: AjusteManual): void {
  client.setQueryData<Escena>(escenaKey, (actual) => {
    if (!actual) return actual;
    return {
      ...actual,
      elementos: actual.elementos.map((e) => {
        if (e.id !== objetoId || e.tipo !== "objeto" || ajuste.restablecer) return e;
        if (ajuste.parte) {
          const ajustes = { ...(e.ajustes ?? {}) };
          ajustes[ajuste.parte] = {
            ...ajustes[ajuste.parte],
            posicion: ajuste.posicion,
            rotacion: ajuste.rotacion,
            escala: ajuste.escala,
          };
          return { ...e, ajustes, manual: true };
        }
        return {
          ...e,
          posicion: ajuste.posicion?.map(String) ?? e.posicion,
          rotacion: ajuste.rotacion?.map(String) ?? e.rotacion,
          escala: ajuste.escala?.map(String) ?? e.escala,
          manual: true,
        };
      }),
    };
  });
}

/** El objeto tal como quedó en el servidor, sin esperar al WebSocket. */
export function aplicarObjeto(client: QueryClient, objeto: Objeto): void {
  client.setQueryData<Escena>(escenaKey, (actual) =>
    actual ? { ...actual, elementos: actual.elementos.map((e) => (e.id === objeto.id ? objeto : e)) } : actual,
  );
}
