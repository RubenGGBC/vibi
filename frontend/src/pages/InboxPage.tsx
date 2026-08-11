import { useMutation, useQuery } from "@tanstack/react-query";
import { SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { MessageComposer } from "../components/MessageComposer";
import { TaskCard } from "../components/TaskCard";
import { ApiError, apiFetch } from "../lib/api";
import { orderTasks, taskKeys } from "../lib/tasks";
import type { MessageResponse, Task } from "../types";

interface ProjectsResponse {
  proyectos: string[];
}

interface AISettingsResponse {
  agent_model: string;
}

export function InboxPage() {
  const navigate = useNavigate();
  const [state, setState] = useState("");
  const [project, setProject] = useState("");
  const [feedback, setFeedback] = useState("");
  const [modelo, setModelo] = useState("claude-sonnet-5");
  const query = useQuery({
    queryKey: taskKeys.list(state, project),
    queryFn: () => {
      const params = new URLSearchParams({ limite: "100" });
      if (state) params.set("estado", state);
      if (project) params.set("proyecto", project);
      return apiFetch<Task[]>(`/api/tareas?${params}`);
    },
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => apiFetch<ProjectsResponse>("/api/proyectos"),
  });
  const aiSettings = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => apiFetch<AISettingsResponse>("/api/configuracion/ia"),
  });
  useEffect(() => {
    if (aiSettings.data?.agent_model) setModelo(aiSettings.data.agent_model);
  }, [aiSettings.data?.agent_model]);
  const createTask = useMutation({
    mutationFn: ({ texto, modelo }: { texto: string; modelo: string }) =>
      apiFetch<MessageResponse>("/api/mensaje", {
        method: "POST",
        body: JSON.stringify({ texto, modelo }),
      }),
    onSuccess: (result) => {
      if (result.via === "agentica") navigate(`/tareas/${result.task_id}`);
      else setFeedback(result.respuesta);
    },
    onError: (reason) => {
      setFeedback(reason instanceof ApiError ? reason.message : "No se pudo crear la tarea");
    },
  });
  const tasks = orderTasks(
    (query.data ?? []).filter(
      (task) =>
        (!state || task.estado === state) &&
        (!project ||
          task.proyecto?.toLocaleLowerCase() === project.toLocaleLowerCase()),
    ),
  );

  return (
    <section className="page inbox-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Ahora</p>
          <h1>Bandeja</h1>
          <p>Planes que esperan tu mirada y trabajo que sigue en marcha.</p>
        </div>
        <span className="live-indicator"><i /> En vivo</span>
      </header>

      <div className="new-task-panel">
        <p className="panel-label">Nuevo encargo</p>
        <label className="model-picker">
          <span>Modelo de Claude</span>
          <select value={modelo} onChange={(event) => setModelo(event.target.value)}>
            <option value="claude-sonnet-5">Sonnet 5</option>
            <option value="claude-fable-5">Fable 5</option>
            <option value="claude-opus-4-8">Opus 4.8</option>
            <option value="claude-haiku-4-5">Haiku 4.5</option>
          </select>
        </label>
        <MessageComposer
          label="Nuevo encargo"          placeholder="Describe el cambio e incluye el proyecto…"
          submitLabel="Crear tarea"
          autoFocus
          pending={createTask.isPending}
          onSubmit={(text) =>
            createTask.mutateAsync({ texto: text, modelo }).then(() => undefined)
          }
        />
        {feedback && <p className="composer-feedback" role="status">{feedback}</p>}
      </div>

      <div className="filter-row">
        <span><SlidersHorizontal size={15} /> Filtrar</span>
        <label>
          <span className="sr-only">Estado</span>
          <select value={state} onChange={(event) => setState(event.target.value)}>
            <option value="">Todos los estados</option>
            {[
              ["esperando_aprobacion", "Requiere aprobación"],
              ["pendiente", "Pendiente"],
              ["planificando", "Planificando"],
              ["ejecutando", "En ejecución"],
              ["completada", "Completada"],
              ["rechazada", "Rechazada"],
              ["error", "Error"],
            ].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          <span className="sr-only">Proyecto</span>
          <select value={project} onChange={(event) => setProject(event.target.value)}>
            <option value="">Todos los proyectos</option>
            {projects.data?.proyectos.map((name) => <option key={name}>{name}</option>)}
          </select>
        </label>
      </div>

      {query.isPending ? (
        <div className="loading-list" aria-label="Cargando tareas"><i /><i /><i /></div>
      ) : query.isError ? (
        <p className="inline-error">No se pudo cargar la bandeja.</p>
      ) : tasks.length ? (
        <ul className="task-list" aria-label="Tareas">
          {tasks.map((task) => <TaskCard key={task.id} task={task} />)}
        </ul>
      ) : (
        <div className="empty-list">
          <h2>La bandeja está despejada</h2>
          <p>Escribe un encargo arriba para poner a Vibi a trabajar.</p>
        </div>
      )}
    </section>
  );
}
