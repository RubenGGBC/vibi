import { apiFetch } from "./api";
import type { EquipoHumano, EquipoPanel, SeguimientoEquipo } from "../types";

export const equiposKey = ["equipos-humanos"] as const;
export const equipoPanelKey = (id: string) => ["equipos-humanos", id] as const;
export const seguimientosPendientesKey = ["equipos-humanos", "pendientes"] as const;

export async function fetchEquipos(): Promise<EquipoHumano[]> {
  const data = await apiFetch<{ equipos: EquipoHumano[] }>("/api/equipos");
  return data.equipos ?? [];
}

export async function crearEquipo(nombre: string): Promise<EquipoHumano> {
  const data = await apiFetch<{ equipo: EquipoHumano }>("/api/equipos", {
    method: "POST",
    body: JSON.stringify({ nombre }),
  });
  return data.equipo;
}

export async function fetchEquipoPanel(id: string): Promise<EquipoPanel> {
  return apiFetch<EquipoPanel>(`/api/equipos/${encodeURIComponent(id)}`);
}

export async function anadirMiembro(id: string, nombre: string): Promise<void> {
  await apiFetch(`/api/equipos/${encodeURIComponent(id)}/miembros`, {
    method: "POST",
    body: JSON.stringify({ nombre }),
  });
}

export async function crearTareaEquipo(
  id: string,
  titulo: string,
  asignada_a: string,
): Promise<void> {
  await apiFetch(`/api/equipos/${encodeURIComponent(id)}/tareas`, {
    method: "POST",
    body: JSON.stringify({ titulo, asignada_a }),
  });
}

export async function declararEstadoTarea(
  equipoId: string,
  tareaId: number,
  estado: "abierta" | "en_progreso" | "esperando_revision" | "entregada" | "cerrada",
): Promise<void> {
  await apiFetch(
    `/api/equipos/${encodeURIComponent(equipoId)}/tareas/${tareaId}/declarar`,
    { method: "POST", body: JSON.stringify({ estado }) },
  );
}

export async function proponerSeguimiento(
  equipoId: string,
  payload: {
    tarea_id: number;
    node_id?: string;
    senal: "avance" | "sin_avance" | "entregado";
    parametros: Record<string, unknown>;
    justificacion: string;
  },
): Promise<void> {
  await apiFetch(`/api/equipos/${encodeURIComponent(equipoId)}/seguimientos`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchSeguimientosPendientes(): Promise<SeguimientoEquipo[]> {
  const data = await apiFetch<{ seguimientos: SeguimientoEquipo[] }>(
    "/api/equipos/seguimientos/pendientes",
  );
  return data.seguimientos ?? [];
}

export async function decidirSeguimiento(
  id: string,
  decision: "aprobar" | "rechazar" | "revocar",
): Promise<void> {
  await apiFetch(
    `/api/equipos/seguimientos/${encodeURIComponent(id)}/${decision}`,
    { method: "POST" },
  );
}
