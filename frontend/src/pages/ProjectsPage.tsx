import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderGit2, GitBranch, Plus } from "lucide-react";
import { useState } from "react";

import { CloneProjectDialog } from "../components/CloneProjectDialog";
import { ApiError, apiFetch } from "../lib/api";

interface ProjectsResponse { proyectos: string[] }
interface CloneResponse { proyecto: string }

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
      {query.isPending ? (
        <div className="project-grid"><i className="project-skeleton" /><i className="project-skeleton" /></div>
      ) : query.isError ? (
        <p className="inline-error">No se pudieron leer los proyectos.</p>
      ) : query.data?.proyectos.length ? (
        <ul className="project-grid" aria-label="Proyectos">
          {query.data.proyectos.map((name) => (
            <li key={name} className="project-card">
              <span className="project-icon"><FolderGit2 size={23} /></span>
              <div><h2>{name}</h2><p><GitBranch size={13} /> Listo para encargos</p></div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty-list"><h2>Aún no hay proyectos</h2><p>Clona el primero para empezar a crear tareas.</p></div>
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
