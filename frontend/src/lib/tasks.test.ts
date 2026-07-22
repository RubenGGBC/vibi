import { describe, expect, it } from "vitest";

import type { Task } from "../types";
import { orderTasks, upsertTask } from "./tasks";

const task = (
  id: string,
  estado: Task["estado"],
  creado_en: number,
): Task => ({
  id,
  user_id: "u1",
  prompt: id,
  estado,
  plan: null,
  resultado: null,
  workspace: `/workspace/${id}`,
  modelo: "claude-sonnet-5",
  proyecto: id,
  creado_en,
  actualizado_en: creado_en,
});

describe("orderTasks", () => {
  it("prioriza aprobación, activas y después fecha", () => {
    const result = orderTasks([
      task("old-done", "completada", 1),
      task("running", "ejecutando", 2),
      task("new-done", "completada", 4),
      task("approval", "esperando_aprobacion", 3),
      task("planning", "planificando", 5),
    ]);

    expect(result.map(({ id }) => id)).toEqual([
      "approval",
      "planning",
      "running",
      "new-done",
      "old-done",
    ]);
  });

  it("no muta la lista recibida", () => {
    const source = [task("done", "completada", 1), task("wait", "pendiente", 2)];
    orderTasks(source);
    expect(source.map(({ id }) => id)).toEqual(["done", "wait"]);
  });
});

describe("upsertTask", () => {
  it("reemplaza una tarea existente y conserva orden", () => {
    const updated = task("one", "esperando_aprobacion", 1);
    const result = upsertTask(
      [task("one", "planificando", 1), task("two", "completada", 2)],
      updated,
    );
    expect(result[0]).toEqual(updated);
    expect(result).toHaveLength(2);
  });
});
