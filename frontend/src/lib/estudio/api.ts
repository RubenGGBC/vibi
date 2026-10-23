import type { QueryClient } from "@tanstack/react-query";

import { apiFetch } from "../api";
import type { Escena } from "./tipos";

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
  client.setQueryData<Escena>(escenaKey, (actual) =>
    actual ? { ...actual, paso_actual: indice } : actual,
  );
}
