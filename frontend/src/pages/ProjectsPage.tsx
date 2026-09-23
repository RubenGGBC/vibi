import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FolderGit2,
  FolderPlus,
  GitBranch,
  MessagesSquare,
  Paperclip,
  Plus,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";

import { CloneProjectDialog } from "../components/CloneProjectDialog";
import { NewProjectDialog } from "../components/NewProjectDialog";
import { ApiError, apiFetch } from "../lib/api";
import { borrarProyecto, crearProyecto, listarProyectos, projectsKey } from "../lib/proyectos";

interface CloneResponse { proyecto: string }

// Cada proyecto se reconoce por su monograma y un matiz propio dentro de la
// franja violeta de Vibi, para que el listado no sea un muro de clones.
const monogram = (name: string) => {
  const parts = name.replace(/[._\-/]+/g, " ").trim().split(/\s+/).filter(Boolean);
  const source = parts.length >= 2 ? parts[0][0] + parts[1][0] : name.replace(/[^\p{L}\p{N}]/gu, "");
  return source.slice(0, 2).toUpperCase() || "··";
};

const hueFor = (name: string) => {
  let hash = 0;
  for (let index = 0; index < name.length; index += 1) {
    hash = (hash * 31 + name.charCodeAt(index)) % 4096;
  }
  return 248 + (hash % 64); // violeta → orquídea, siempre en paleta
};

export function ProjectsPage() {
  const client = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [nuevoAbierto, setNuevoAbierto] = useState(false);
  const [success, setSuccess] = useState("");
  const query = useQuery({ queryKey: projectsKey, queryFn: listarProyectos });
  const crear = useMutation({
    mutationFn: ({ nombre, descripcion }: { nombre: string; descripcion: string }) =>
      crearProyecto(nombre, descripcion),
    onSuccess: async (proyecto) => {
      await client.invalidateQueries({ queryKey: projectsKey });
      setSuccess(`${proyecto.nombre} está listo.`);
      setNuevoAbierto(false);
    },
  });
  const clone = useMutation({
    mutationFn: (url: string) =>
      apiFetch<CloneResponse>("/api/proyectos/clonar", {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
    onSuccess: async ({ proyecto }) => {
      await client.invalidateQueries({ queryKey: projectsKey });
      setSuccess(`${proyecto} ya está disponible.`);
      setDialogOpen(false);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => borrarProyecto(id),
    onSuccess: async (_, id) => {
      const borrado = query.data?.detalles.find((proyecto) => proyecto.id === id);
      await Promise.all([
        client.invalidateQueries({ queryKey: projectsKey }),
        client.invalidateQueries({ queryKey: ["files"] }),
      ]);
      setSuccess(`${borrado?.nombre ?? "El proyecto"} se ha eliminado.`);
    },
  });
  const removeError =
    remove.error instanceof ApiError
      ? remove.error.message
      : remove.error
        ? "No se pudo eliminar el proyecto."
        : null;
  const proyectos = query.data?.detalles ?? [];

  return (
    <section className="page projects-page">
      <header className="page-header projects-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Proyectos</h1>
          <p>Espacios donde subir archivos, guardar conversaciones y darle trabajo a Vibi.</p>
        </div>
        <div className="projects-header-actions">
          <button className="primary-button clone-trigger" onClick={() => {
            crear.reset(); setSuccess(""); setNuevoAbierto(true);
          }}><FolderPlus size={18} /> Nuevo proyecto</button>
          <button className="secondary-button clone-trigger" onClick={() => {
            clone.reset(); setSuccess(""); setDialogOpen(true);
          }}><Plus size={18} /> Clonar repo</button>
        </div>
      </header>

      {success && <p className="success-message" role="status">{success}</p>}
      {removeError && <p className="inline-error" role="alert">{removeError}</p>}
      {query.isPending ? (
        <div className="project-grid"><i className="project-skeleton" /><i className="project-skeleton" /></div>
      ) : query.isError ? (
        <p className="inline-error">No se pudieron leer los proyectos.</p>
      ) : proyectos.length ? (
        <ul className="project-grid" aria-label="Proyectos">
          {proyectos.map((proyecto) => (
            <li key={proyecto.id} className="project-card">
              <Link className="project-open" to={`/proyectos/${proyecto.id}`}>
                <span className="project-icon" aria-hidden style={{ "--sigil-hue": hueFor(proyecto.slug) } as CSSProperties}>
                  {monogram(proyecto.nombre)}
                </span>
                <div className="project-copy">
                  <h2>{proyecto.nombre}</h2>
                  <p className="project-meta">
                    <span><Paperclip size={12} /> {proyecto.archivos}</span>
                    <span><MessagesSquare size={12} /> {proyecto.conversaciones}</span>
                    {proyecto.carpeta ? (
                      <span><GitBranch size={12} /> Listo para tareas</span>
                    ) : (
                      <span className="project-warning">
                        <TriangleAlert size={12} /> Sin carpeta
                      </span>
                    )}
                  </p>
                </div>
              </Link>
              <button
                className="icon-button danger-button project-delete"
                aria-label={`Eliminar proyecto ${proyecto.nombre}`}
                disabled={remove.isPending}
                onClick={() => {
                  const confirmed = window.confirm(
                    `¿Eliminar el proyecto ${proyecto.nombre}? Se borrará su carpeta; los archivos subidos y las conversaciones guardadas se quedan sueltos en tu espacio.`,
                  );
                  if (confirmed) {
                    setSuccess("");
                    remove.reset();
                    remove.mutate(proyecto.id);
                  }
                }}
              >
                <Trash2 size={17} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty-list">
          <FolderGit2 size={32} />
          <h2>Aún no hay proyectos</h2>
          <p>Crea el primero para tener dónde guardar archivos y conversaciones.</p>
        </div>
      )}

      {nuevoAbierto && (
        <NewProjectDialog
          pending={crear.isPending}
          error={crear.error instanceof ApiError ? crear.error.message : crear.error ? "No se pudo crear el proyecto" : undefined}
          onClose={() => setNuevoAbierto(false)}
          onCreate={(nombre, descripcion) =>
            crear.mutateAsync({ nombre, descripcion }).then(() => undefined)
          }
        />
      )}
      {dialogOpen && (
        <CloneProjectDialog
          pending={clone.isPending}
          error={clone.error instanceof ApiError ? clone.error.message : clone.error ? "No se pudo clonar el repositorio" : undefined}
          onClose={() => setDialogOpen(false)}
          onClone={(url) => clone.mutateAsync(url).then(() => undefined)}
        />
      )}
    </section>
  );
}
