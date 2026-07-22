import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { Task } from "../types";
import { taskKeys } from "./tasks";
import { applyServerEvent } from "./useEvents";

const makeTask = (estado: Task["estado"]): Task => ({
  id: "t1",
  user_id: "u1",
  prompt: "Haz algo",
  estado,
  plan: null,
  resultado: null,
  workspace: "/workspace/morgana",
  modelo: "claude-sonnet-5",
  proyecto: "morgana",
  creado_en: 1,
  actualizado_en: 2,
});

describe("applyServerEvent", () => {
  it("actualiza todas las listas y el detalle sin refetch", () => {
    const client = new QueryClient();
    client.setQueryData(taskKeys.list(), [makeTask("planificando")]);
    client.setQueryData(taskKeys.list("planificando"), [makeTask("planificando")]);
    client.setQueryData(taskKeys.detail("t1"), makeTask("planificando"));
    const updated = { ...makeTask("esperando_aprobacion"), plan: "## Plan" };

    applyServerEvent(client, { tipo: "tarea_actualizada", task: updated });

    expect(client.getQueryData<Task[]>(taskKeys.list())?.[0]).toEqual(updated);
    expect(
      client.getQueryData<Task[]>(taskKeys.list("planificando"))?.[0],
    ).toEqual(updated);
    expect(client.getQueryData<Task>(taskKeys.detail("t1"))).toEqual(updated);
  });
});
