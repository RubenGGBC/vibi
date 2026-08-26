import { apiFetch } from "./api";
import type { NodeDevice, NodeOrder } from "../types";

/**
 * La malla, para quien la quiera pintar.
 *
 * `nodes.py` son casi mil líneas —presencia, capacidades, órdenes, trastienda—
 * y hasta ahora lo único que el cliente pedía de ahí eran las aprobaciones. El
 * resto viajaba por el canal y se descartaba, o se quedaba en el servidor.
 */

export const nodosKey = ["nodos"] as const;

export const ordenesDeNodoKey = (nodeId: string) =>
  ["nodos", nodeId, "ordenes"] as const;

export async function fetchNodos(): Promise<NodeDevice[]> {
  const datos = await apiFetch<{ nodos: NodeDevice[] }>("/api/nodos");
  return datos.nodos ?? [];
}

export async function fetchOrdenesDeNodo(nodeId: string): Promise<NodeOrder[]> {
  const datos = await apiFetch<{ ordenes: NodeOrder[] }>(
    `/api/nodos/${encodeURIComponent(nodeId)}/ordenes`,
  );
  return datos.ordenes ?? [];
}

/**
 * Los conectados primero y, dentro de cada grupo, el visto más reciente arriba.
 *
 * Que un equipo apagado baje no es cosmética: la lista se lee para decidir
 * dónde mandar algo, y lo que no está conectado no es un destino.
 */
export function ordenarNodos(nodos: NodeDevice[]): NodeDevice[] {
  return [...nodos].sort((a, b) => {
    if (a.conectado !== b.conectado) return a.conectado ? -1 : 1;
    return (b.last_seen ?? 0) - (a.last_seen ?? 0);
  });
}

/** Hace cuánto se le vio, en palabras. */
export function desdeCuando(marca: number, ahora = Date.now()): string {
  if (!marca) return "nunca";
  const segundos = Math.max(0, Math.round((ahora - marca * 1000) / 1000));
  if (segundos < 60) return `hace ${segundos} s`;
  const minutos = Math.round(segundos / 60);
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 24) return `hace ${horas} h`;
  return `hace ${Math.round(horas / 24)} d`;
}
