import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Clock3, Folder, X } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { MarkdownContent } from "../components/MarkdownContent";
import { StatusBadge } from "../components/StatusBadge";
import { ApiError, apiFetch } from "../lib/api";
import { taskKeys } from "../lib/tasks";
import type { Task } from "../types";

interface ActionResponse { ok: boolean; task: Task }

export function TaskDetailPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: taskKeys.detail(id),
    queryFn: () => apiFetch<Task>(`/api/tareas/${id}`),
    enabled: Boolean(id),
  });
  const action = useMutation({
    mutationFn: (kind: "aprobar" | "rechazar") =>
      apiFetch<ActionResponse>(`/api/tareas/${id}/${kind}`, { method: "POST" }),
    onSuccess: ({ task }) => client.setQueryData(taskKeys.detail(id), task),
  });
  const task = query.data;

  if (query.isPending) return <div className="detail-loading">Consultando el círculo…</div>;
  if (query.isError || !task) {
    return <section className="empty-list"><h1>Tarea no encontrada</h1><Link to="/">Volver</Link></section>;
  }

  return (
    <article className="task-detail">
      <Link to="/" className="back-link"><ArrowLeft size={17} /> Bandeja</Link>
      <header className="detail-header">
        <div className="detail-meta">
          <StatusBadge state={task.estado} />
          <span><Folder size={14} /> {task.proyecto ?? "Sin proyecto"}</span>
        </div>
        <h1>{task.prompt}</h1>
        <div className="detail-times">
          <span><Clock3 size={14} /> Creada {new Date(task.creado_en * 1000).toLocaleString("es")}</span>
          <span>Actualizada {new Date(task.actualizado_en * 1000).toLocaleString("es")}</span>
        </div>
      </header>

      {task.plan && (
        <section className="detail-section">
          <p className="eyebrow">Plan propuesto</p>
          <MarkdownContent>{task.plan}</MarkdownContent>
        </section>
      )}

      {task.estado === "esperando_aprobacion" && (
        <section className="approval-bar" aria-label="Decisión del plan">
          <div><strong>Tu decisión desbloquea el trabajo</strong><span>Revisa el plan antes de continuar.</span></div>
          <button className="reject-button" disabled={action.isPending} onClick={() => action.mutate("rechazar")}><X size={18} /> Rechazar</button>
          <button className="primary-button" disabled={action.isPending} onClick={() => action.mutate("aprobar")} aria-label="Aprobar plan"><Check size={18} /> Aprobar plan</button>
        </section>
      )}
      {action.error && <p className="inline-error">{action.error instanceof ApiError ? action.error.message : "No se pudo actualizar la tarea"}</p>}

      {task.resultado && (
        <section className="detail-section result-section">
          <p className="eyebrow">Resultado</p>
          <MarkdownContent>{task.resultado}</MarkdownContent>
        </section>
      )}
    </article>
  );
}
