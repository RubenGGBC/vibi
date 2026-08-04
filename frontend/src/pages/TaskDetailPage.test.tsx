import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Task } from "../types";
import { TaskDetailPage } from "./TaskDetailPage";

const waiting: Task = {
  id: "t1",
  user_id: "u1",
  prompt: "Implementa el acceso",
  estado: "esperando_aprobacion",
  plan: "## Paso uno\n\n```ts\nconst listo = true\n```",
  resultado: null,
  workspace: "/workspace/morgana",
  modelo: "claude-sonnet-5",
  proyecto: "morgana",
  creado_en: 1,
  actualizado_en: 2,
};

function LocationProbe() {
  return <span data-testid="location">{useLocation().pathname}</span>;
}

describe("TaskDetailPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renderiza markdown y oculta acciones después de aprobar", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/tareas/t1" && !init?.method) return Response.json(waiting);
        if (url === "/api/tareas/t1/aprobar") {
          return Response.json({
            ok: true,
            task: { ...waiting, estado: "ejecutando" },
          });
        }
        return Response.json({ error: "No esperado" }, { status: 500 });
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/tareas/t1"]}>
          <Routes>
            <Route path="/tareas/:id" element={<TaskDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Paso uno" })).toBeInTheDocument();
    expect(screen.getByText("const listo = true")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Aprobar plan" }));
    expect(screen.queryByRole("button", { name: "Aprobar plan" })).not.toBeInTheDocument();
    expect(screen.getByText("En ejecución")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reintentar tarea" })).not.toBeInTheDocument();
  });

  it("crea otro intento para una tarea fallida y abre su detalle", async () => {
    const failed: Task = {
      ...waiting,
      estado: "error",
      plan: null,
      resultado: "La conexión con el agente se interrumpió.",
    };
    const retried: Task = {
      ...failed,
      id: "t2",
      estado: "pendiente",
      resultado: null,
      creado_en: 3,
      actualizado_en: 3,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/tareas/t1" && !init?.method) return Response.json(failed);
        if (url === "/api/tareas/t1/reintentar" && init?.method === "POST") {
          return Response.json({
            ok: true,
            task: retried,
            source_task_id: "t1",
          }, { status: 201 });
        }
        if (url === "/api/tareas/t2" && !init?.method) return Response.json(retried);
        return Response.json({ error: "No esperado" }, { status: 500 });
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/tareas/t1"]}>
          <LocationProbe />
          <Routes>
            <Route path="/tareas/:id" element={<TaskDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(
      await screen.findByRole("button", { name: "Reintentar tarea" }),
    );

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/tareas/t2"));
    expect(await screen.findByText("Pendiente")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reintentar tarea" })).not.toBeInTheDocument();
  });
});
