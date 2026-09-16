import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import type { Task } from "../types";
import { aparienciaKey } from "./apariencia";
import { taskKeys } from "./tasks";
import { applyServerEvent } from "./useEvents";

const makeTask = (estado: Task["estado"]): Task => ({
  id: "t1",
  user_id: "u1",
  prompt: "Haz algo",
  estado,
  plan: null,
  resultado: null,
  workspace: "/workspace/vibi",
  modelo: "claude-sonnet-5",
  proyecto: "vibi",
  creado_en: 1,
  actualizado_en: 2,
});

describe("applyServerEvent", () => {
  it("aplica en caché un cambio de identidad recibido en tiempo real", () => {
    const client = new QueryClient();
    const apariencia = {
      color_cara: "#FCE7F3",
      color_antifaz: "#172554",
      color_sombrero: "#2563EB",
      actualizada_en: 42,
    };

    applyServerEvent(client, { tipo: "apariencia_actualizada", apariencia });

    expect(client.getQueryData(aparienciaKey)).toEqual(apariencia);
  });

  it("actualiza todas las listas y el detalle sin refetch", () => {
    const client = new QueryClient();
    client.setQueryData(taskKeys.list(), [makeTask("planificando")]);
    client.setQueryData(taskKeys.list("planificando"), [makeTask("planificando")]);
    client.setQueryData(taskKeys.detail("t1"), makeTask("planificando"));
    const updated = { ...makeTask("esperando_aprobacion"), plan: "## Plan" };

    applyServerEvent(client, { tipo: "tarea_actualizada", task: updated });

    expect(client.getQueryData<Task[]>(taskKeys.list())?.[0]).toEqual(updated);
    expect(
      client.getQueryData<Task[]>(taskKeys.list("planificando")),
    ).toEqual([]);
    expect(client.getQueryData<Task>(taskKeys.detail("t1"))).toEqual(updated);
  });

  it("marca la actividad como obsoleta cuando cambia trabajo auditable", () => {
    const client = new QueryClient();
    client.setQueryData(["activity", ""], { pages: [] });
    const invalidate = vi.spyOn(client, "invalidateQueries");

    applyServerEvent(client, {
      tipo: "tarea_actualizada",
      task: makeTask("ejecutando"),
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["activity"] });
  });
});
