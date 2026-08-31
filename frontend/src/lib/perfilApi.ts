import { apiFetch } from "./api";
import type {
  Afirmacion,
  Capacidad,
  ClaseAfirmacion,
  DescarteEntrevista,
  Hipotesis,
  NivelCapacidad,
  PerfilUsuario,
  Propuesta,
  TurnoEntrevista,
  TurnoHistorial,
} from "../types";

export const perfilKeys = {
  all: ["perfil"] as const,
  hipotesis: ["perfil", "hipotesis"] as const,
};

export async function fetchPerfil(): Promise<PerfilUsuario> {
  return apiFetch<PerfilUsuario>("/api/perfil");
}

export async function crearAfirmacion(
  clase: ClaseAfirmacion,
  valor: string,
  procedencia = "entrevista",
): Promise<Afirmacion> {
  return apiFetch<Afirmacion>("/api/perfil/afirmaciones", {
    method: "POST",
    body: JSON.stringify({ clase, valor, procedencia }),
  });
}

export async function borrarAfirmacion(id: number): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/perfil/afirmaciones/${id}`, {
    method: "DELETE",
  });
}

export async function aprobarCapacidad(payload: {
  tipo: string;
  referencia: string;
  justificacion: string;
  transporte?: string;
  endpoint?: string;
}): Promise<Capacidad> {
  return apiFetch<Capacidad>("/api/perfil/capacidades/aprobar", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function cambiarNivelCapacidad(
  id: number,
  nivel: NivelCapacidad,
): Promise<{ ok: boolean; nivel: NivelCapacidad }> {
  return apiFetch<{ ok: boolean; nivel: NivelCapacidad }>(
    `/api/perfil/capacidades/${id}/nivel`,
    {
      method: "PUT",
      body: JSON.stringify({ nivel }),
    },
  );
}

export async function borrarCapacidad(id: number): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/perfil/capacidades/${id}`, {
    method: "DELETE",
  });
}

export async function resetearPerfil(): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>("/api/perfil", {
    method: "DELETE",
  });
}

export async function ejecutarRevision(): Promise<{
  apoyadas: string[];
  decaidas: string[];
  propuestas_retirada: string[];
  omitida: boolean;
}> {
  return apiFetch<{
    apoyadas: string[];
    decaidas: string[];
    propuestas_retirada: string[];
    omitida: boolean;
  }>("/api/perfil/revision", {
    method: "POST",
  });
}

export async function fetchHipotesis(): Promise<{
  hipotesis: Hipotesis[];
  tiene_nodo: boolean;
}> {
  return apiFetch<{ hipotesis: Hipotesis[]; tiene_nodo: boolean }>(
    "/api/perfil/entrevista/hipotesis",
  );
}

export async function generarPropuestas(
  terminos_pedidos: string[],
  terminos_adyacentes: string[],
  texto_libre = "",
  texto_libre_adyacente = "",
): Promise<Propuesta[]> {
  return apiFetch<Propuesta[]>("/api/perfil/entrevista/propuesta", {
    method: "POST",
    body: JSON.stringify({
      terminos_pedidos,
      terminos_adyacentes,
      texto_libre,
      texto_libre_adyacente,
    }),
  });
}

export async function turnoEntrevista(
  historial: TurnoHistorial[],
): Promise<TurnoEntrevista> {
  return apiFetch<TurnoEntrevista>("/api/perfil/entrevista/turno", {
    method: "POST",
    body: JSON.stringify({ historial }),
  });
}

/** Sube un clip corto y devuelve solo la transcripción, sin enrutar a Vibi. */
export async function transcribirEntrevista(
  audio: Blob,
  filename: string,
): Promise<{ transcripcion: string }> {
  const body = new FormData();
  body.append("audio", audio, filename);
  return apiFetch<{ transcripcion: string }>("/api/perfil/entrevista/voz", {
    method: "POST",
    body,
  });
}

export async function completarEntrevista(payload: {
  afirmaciones: Array<{
    clase: ClaseAfirmacion;
    valor: string;
    procedencia?: string;
  }>;
  capacidades: Array<{
    tipo: string;
    referencia: string;
    justificacion: string;
    transporte?: string;
    endpoint?: string;
    paquete?: string;
  }>;
  resumen?: string;
}): Promise<PerfilUsuario & { descartes?: DescarteEntrevista[] }> {
  return apiFetch<PerfilUsuario & { descartes?: DescarteEntrevista[] }>(
    "/api/perfil/entrevista/completar",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
