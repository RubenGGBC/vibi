import { apiFetch } from "./api";
import type {
  Project,
  ProjectsResponse,
  SavedConversation,
  UserFile,
} from "../types";

export const projectsKey = ["projects"] as const;
export const projectKey = (id: string) => ["project", id] as const;
export const projectFilesKey = (id: string) => ["project", id, "files"] as const;
export const projectConversationsKey = (id: string) =>
  ["project", id, "conversations"] as const;

export const listarProyectos = () =>
  apiFetch<ProjectsResponse>("/api/proyectos");

export const crearProyecto = (nombre: string, descripcion: string) =>
  apiFetch<Project>("/api/proyectos", {
    method: "POST",
    body: JSON.stringify({ nombre, descripcion }),
  });

export const actualizarProyecto = (
  id: string,
  cambios: { nombre?: string; descripcion?: string },
) =>
  apiFetch<Project>(`/api/proyectos/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(cambios),
  });

export const borrarProyecto = (id: string) =>
  apiFetch<void>(`/api/proyectos/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const verProyecto = (id: string) =>
  apiFetch<Project>(`/api/proyectos/${encodeURIComponent(id)}`);

export const archivosDelProyecto = (id: string) =>
  apiFetch<{ proyecto: Project; archivos: UserFile[] }>(
    `/api/proyectos/${encodeURIComponent(id)}/archivos`,
  );

export const subirAlProyecto = (id: string, archivo: globalThis.File) => {
  const data = new FormData();
  data.append("archivo", archivo);
  return apiFetch<UserFile>(
    `/api/proyectos/${encodeURIComponent(id)}/archivos`,
    { method: "POST", body: data },
  );
};

/** Saca el archivo del proyecto. No lo borra: sigue en tus archivos. */
export const sacarDelProyecto = (id: string, fileId: string) =>
  apiFetch<void>(
    `/api/proyectos/${encodeURIComponent(id)}/archivos/${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
  );

export const conversacionesDelProyecto = (id: string) =>
  apiFetch<{ proyecto: Project; conversaciones: SavedConversation[] }>(
    `/api/proyectos/${encodeURIComponent(id)}/conversaciones`,
  );

export const guardarConversacionActiva = (
  projectId: string | null,
  titulo?: string,
) =>
  apiFetch<SavedConversation>("/api/conversations/active/guardar", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, titulo }),
  });

export const reanudarConversacion = (conversationId: string) =>
  apiFetch<import("../types").ConversationState>(
    `/api/conversaciones/${encodeURIComponent(conversationId)}/reanudar`,
    { method: "POST" },
  );
