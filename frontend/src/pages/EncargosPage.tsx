import { useQuery } from "@tanstack/react-query";
import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";

import { TaskCard } from "../components/TaskCard";
import { apiFetch } from "../lib/api";
import { orderTasks, taskKeys } from "../lib/tasks";
import type { Task } from "../types";

interface ProjectsResponse {
  proyectos: string[];
}

const STATES: [string, string][] = [
  ["esperando_aprobacion", "Requiere aprobación"],
  ["pendiente", "Pendiente"],
  ["planificando", "Planificando"],
  ["ejecutando", "En ejecución"],
  ["completada", "Completada"],
  ["rechazada", "Rechazada"],
  ["error", "Error"],
];

export function EncargosPage() {
  const [state, setState] = useState("");
  const [project, setProject] = useState("");
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
  const tasks = orderTasks(
    (query.data ?? []).filter(
      (task) =>
        (!state || task.estado === state) &&
        (!project ||
          task.proyecto?.toLocaleLowerCase() === project.toLocaleLowerCase()),
    ),
  );

  return (
    <section className="encargos-page" aria-label="Encargos">
      <header className="bandeja-head">
        <div>
          <p className="eyebrow">Lo que sobrevive al turno</p>
          <h2>Encargos</h2>
        </div>
        <span className="live-indicator"><i /> En vivo</span>
      </header>

      <div className="filter-row">
        <span><SlidersHorizontal size={15} /> Filtrar</span>
        <label>
          <span className="sr-only">Estado</span>
          <select value={state} onChange={(event) => setState(event.target.value)}>
            <option value="">Todos los estados</option>
            {STATES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
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

      <div className="bandeja-list">
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
            <h2>Ningún encargo abierto</h2>
            <p>Pídeselo desde el Hilo o hablando, y lo que dé para tarea aparecerá aquí.</p>
          </div>
        )}
      </div>
    </section>
  );
}
