import { ArrowUpRight, Folder } from "lucide-react";
import { Link } from "react-router-dom";

import { relativeTime } from "../lib/tasks";
import type { Task } from "../types";
import { StatusBadge } from "./StatusBadge";

const active = new Set<Task["estado"]>([
  "pendiente",
  "planificando",
  "esperando_aprobacion",
  "ejecutando",
]);

export function TaskCard({ task }: { task: Task }) {
  return (
    <li data-testid="task-card" data-task-id={task.id}>
      <Link
        to={`/tareas/${task.id}`}
        className={`task-card ${active.has(task.estado) ? "task-card-active" : ""}`}
        aria-label={`Abrir tarea: ${task.prompt}`}
      >
        {active.has(task.estado) && <span className="spell-thread" aria-hidden="true" />}
        <div className="task-card-topline">
          <StatusBadge state={task.estado} />
          <time dateTime={new Date(task.creado_en * 1000).toISOString()}>
            {relativeTime(task.creado_en)}
          </time>
        </div>
        <h2>{task.prompt}</h2>
        <div className="task-card-footer">
          <span>
            <Folder size={13} />
            {task.proyecto ?? "Sin proyecto"}
          </span>
          <ArrowUpRight size={17} aria-hidden="true" />
        </div>
      </Link>
    </li>
  );
}
