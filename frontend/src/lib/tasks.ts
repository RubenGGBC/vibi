import type { Task } from "../types";

const activeStates = new Set<Task["estado"]>([
  "pendiente",
  "planificando",
  "ejecutando",
]);

const rank = (task: Task): number => {
  if (task.estado === "esperando_aprobacion") return 0;
  if (activeStates.has(task.estado)) return 1;
  return 2;
};

export const orderTasks = (tasks: Task[]): Task[] =>
  [...tasks].sort((left, right) => {
    const rankDifference = rank(left) - rank(right);
    if (rankDifference !== 0) return rankDifference;
    return right.creado_en - left.creado_en;
  });

export const upsertTask = (tasks: Task[] = [], updated: Task): Task[] =>
  orderTasks([...tasks.filter(({ id }) => id !== updated.id), updated]);

export const taskKeys = {
  all: ["tasks"] as const,
  list: (estado?: string, proyecto?: string) =>
    ["tasks", { estado: estado ?? "", proyecto: proyecto ?? "" }] as const,
  detail: (id: string) => ["task", id] as const,
};

export const relativeTime = (timestamp: number): string => {
  const seconds = Math.round(timestamp - Date.now() / 1000);
  const formatter = new Intl.RelativeTimeFormat("es", { numeric: "auto" });
  const ranges: Array<[number, Intl.RelativeTimeFormatUnit]> = [
    [86_400, "day"],
    [3_600, "hour"],
    [60, "minute"],
  ];
  for (const [size, unit] of ranges) {
    if (Math.abs(seconds) >= size) {
      return formatter.format(Math.round(seconds / size), unit);
    }
  }
  return formatter.format(seconds, "second");
};
