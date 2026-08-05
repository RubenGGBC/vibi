import type { QueryClient } from "@tanstack/react-query";

import type { NodeOrder } from "../types";
import { apiFetch } from "./api";

export const nodeApprovalsKey = ["nodos", "aprobaciones"] as const;

export async function fetchNodeApprovals(): Promise<NodeOrder[]> {
  const payload = await apiFetch<{ ordenes: NodeOrder[] }>(
    "/api/nodos/aprobaciones",
  );
  return payload.ordenes;
}

export async function approveNodeOrder(orderId: string): Promise<void> {
  await apiFetch(`/api/nodos/ordenes/${orderId}/aprobar`, { method: "POST" });
}

export async function rejectNodeOrder(orderId: string): Promise<void> {
  await apiFetch(`/api/nodos/ordenes/${orderId}/rechazar`, { method: "POST" });
}

/** Añade una orden a la cola sin duplicarla si el evento llega dos veces. */
export function upsertApproval(
  current: NodeOrder[] | undefined,
  order: NodeOrder,
): NodeOrder[] {
  const rest = (current ?? []).filter(({ id }) => id !== order.id);
  return [order, ...rest];
}

export function removeApproval(
  current: NodeOrder[] | undefined,
  orderId: string,
): NodeOrder[] {
  return (current ?? []).filter(({ id }) => id !== orderId);
}

export function applyApprovalEvent(
  client: QueryClient,
  order: NodeOrder,
  pending: boolean,
): void {
  client.setQueryData<NodeOrder[]>(nodeApprovalsKey, (current) =>
    pending ? upsertApproval(current, order) : removeApproval(current, order.id),
  );
  // Escribir en la caché es lo que hace que la tarjeta salga al instante, pero
  // una consulta que ya estuviera en vuelo llegaría después con una lista sin
  // esta orden y la borraría de la pantalla. Pedir una relectura cierra esa
  // ventana: el servidor la tiene guardada y la va a devolver igual.
  void client.invalidateQueries({ queryKey: nodeApprovalsKey });
}

/** Frase corta para la tarjeta: qué va a pasar exactamente si apruebas. */
export function describeOrder(order: NodeOrder): string {
  const donde = order.node_nombre ?? "otro dispositivo";
  if (order.capability === "shell.run") {
    return `Ejecutar en ${donde}`;
  }
  if (order.capability === "browser.open") {
    return `Abrir una web en ${donde}`;
  }
  if (order.capability === "open.path") {
    return `Abrir un archivo en ${donde}`;
  }
  if (order.capability === "files.search") {
    return `Buscar archivos en ${donde}`;
  }
  return `${order.capability} en ${donde}`;
}

/** El texto literal que se va a ejecutar, para que puedas leerlo antes. */
export function orderPayload(order: NodeOrder): string {
  const args = (order.arguments ?? {}) as Record<string, unknown>;
  const candidatos = ["comando", "url", "ruta", "patron"];
  for (const clave of candidatos) {
    const valor = args[clave];
    if (typeof valor === "string" && valor.trim()) return valor;
  }
  return JSON.stringify(args);
}
