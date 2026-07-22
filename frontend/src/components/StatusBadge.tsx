import type { TaskState } from "../types";

const labels: Record<TaskState, string> = {
  pendiente: "Pendiente",
  planificando: "Planificando",
  esperando_aprobacion: "Requiere aprobación",
  ejecutando: "En ejecución",
  completada: "Completada",
  rechazada: "Rechazada",
  error: "Error",
};

export function StatusBadge({ state }: { state: TaskState }) {
  return <span className={`status-badge status-${state}`}>{labels[state]}</span>;
}
