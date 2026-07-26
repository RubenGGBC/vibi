import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderGit2, GitBranch, Plus, Trash2 } from "lucide-react";
import { useState, type CSSProperties } from "react";

import { CloneProjectDialog } from "../components/CloneProjectDialog";
import { ApiError, apiFetch } from "../lib/api";

interface ProjectsResponse { proyectos: string[] }
interface CloneResponse { proyecto: string }

// Cada proyecto se reconoce por su monograma y un matiz propio dentro de la
// franja violeta de Morgana, para que el listado no sea un muro de clones.
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
  const [success, setSuccess] = useState("");
  const query = useQuery({
    queryKey: ["projects"],
    queryFn: () => apiFetch<ProjectsResponse>("/api/proyectos"),
  });
  const clone = useMutation({
    mutationFn: (url: string) =>
      apiFetch<CloneResponse>("/api/proyectos/clonar", {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
    onSuccess: async ({ proyecto }) => {
      await client.invalidateQueries({ queryKey: ["projects"] });
      setSuccess(`${proyecto} ya está disponible.`);
      setDialogOpen(false);
    },
  });
  const remove = useMutation({
    mutationFn: (name: string) =>
      apiFetch<void>(`/api/proyectos/${encodeURIComponent(name)}`, {
        method: "DELETE",
      }),
    onSuccess: async (_, name) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["projects"] }),
        client.invalidateQueries({ queryKey: ["files"] }),
      ]);
      setSuccess(`${name} se ha eliminado.`);
    },
  });
  const removeError =
    remove.error instanceof ApiError
      ? remove.error.message
      : remove.error
        ? "No se pudo eliminar el proyecto."
        : null;

  return (
    <section className="page projects-page">
      <header className="page-header projects-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Proyectos</h1>
          <p>Repositorios donde Morgana puede analizar, planificar y trabajar.</p>
        </div>
        <button className="primary-button clone-trigger" onClick={() => {
          clone.reset(); setSuccess(""); setDialogOpen(true);
        }}><Plus size={18} /> Clonar repo</button>
      </header>

      {success && <p className="success-message" role="status">{success}</p>}
      {removeError && <p className="inline-error" role="alert">{removeError}</p>}
      {query.isPending ? (
        <div className="project-grid"><i className="project-skeleton" /><i className="project-skeleton" /></div>
      ) : query.isError ? (
        <p className="inline-error">No se pudieron leer los proyectos.</p>
      ) : query.data?.proyectos.length ? (
        <ul className="project-grid" aria-label="Proyectos">
          {query.data.proyectos.map((name) => (
            <li key={name} className="project-card">
              <span className="project-icon" aria-hidden style={{ "--sigil-hue": hueFor(name) } as CSSProperties}>
                {monogram(name)}
              </span>
              <div className="project-copy"><h2>{name}</h2><p><GitBranch size={13} /> Listo para tareas</p></div>
              <button
                className="icon-button danger-button project-delete"
                aria-label={`Eliminar proyecto ${name}`}
                disabled={remove.isPending}
                onClick={() => {
                  const confirmed = window.confirm(
                    `¿Eliminar el proyecto ${name}? Se borrarán permanentemente todos sus archivos.`,
                  );
                  if (confirmed) {
                    setSuccess("");
                    remove.reset();
                    remove.mutate(name);
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
          <p>Clona el primero para empezar a crear tareas.</p>
        </div>
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
