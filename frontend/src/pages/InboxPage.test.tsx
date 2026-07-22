import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Task } from "../types";
import { InboxPage } from "./InboxPage";

const makeTask = (id: string, estado: Task["estado"], created: number): Task => ({
  id,
  user_id: "u1",
  prompt: `Prompt ${id}`,
  estado,
  plan: null,
  resultado: null,
  workspace: `/workspace/${id}`,
  modelo: "claude-sonnet-5",
  proyecto: id,
  creado_en: created,
  actualizado_en: created,
});

describe("InboxPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("ordena tareas y navega al encargo recién encolado", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/tareas")) return Response.json(tasks);
      if (url === "/api/proyectos") {
        return Response.json({ proyectos: ["approval", "running"] });
      }
      if (url === "/api/mensaje" && init?.method === "POST") {
        return Response.json({ via: "agentica", task_id: "new-task" });
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    const tasks = [
      makeTask("done", "completada", 4),
      makeTask("approval", "esperando_aprobacion", 1),
      makeTask("running", "ejecutando", 3),
    ];
    vi.stubGlobal("fetch", fetchMock);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<InboxPage />} />
            <Route path="/tareas/:id" element={<p>Detalle nuevo</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const list = await screen.findByRole("list", { name: "Tareas" });
    expect(
      within(list).getAllByTestId("task-card").map((card) => card.dataset.taskId),
    ).toEqual(["approval", "running", "done"]);

    await userEvent.selectOptions(
      screen.getByLabelText("Modelo de Claude"),
      "claude-opus-4-8",
    );
    await userEvent.type(screen.getByLabelText("Nuevo encargo"), "Haz el cambio");
    await userEvent.click(screen.getByRole("button", { name: "Crear tarea" }));
    expect(await screen.findByText("Detalle nuevo")).toBeInTheDocument();
    const messageCall = fetchMock.mock.calls.find(([url]) => url === "/api/mensaje");
    expect(JSON.parse(String(messageCall?.[1]?.body))).toEqual({
      texto: "Haz el cambio",
      modelo: "claude-opus-4-8",
    });
  });
});
