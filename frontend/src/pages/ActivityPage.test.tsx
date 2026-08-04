import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActivityPage } from "./ActivityPage";

const summary = {
  tareas_activas: 2,
  esperando_aprobacion: 1,
  tareas_completadas: 12,
  almacenamiento_usado_bytes: 1_500,
  almacenamiento_cuota_bytes: 2_000,
  dispositivos_conocidos: 3,
  dispositivos_recientes: 1,
};

const event = (
  id: number,
  title: string,
  category: string,
  link: string | null = null,
) => ({
  id,
  tipo: title.toLocaleLowerCase().replaceAll(" ", "_"),
  categoria: category,
  titulo: title,
  detalle: "morgana · Pendiente",
  creado_en: 1_700_000_000 + id,
  enlace: link,
});

describe("ActivityPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("muestra el pulso, filtra y pagina la bitácora sin perder eventos", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("categoria=tareas") && url.includes("antes_de=12")) {
        return Response.json({
          resumen: summary,
          eventos: [event(8, "Plan aprobado", "tareas", "/tareas/t1")],
          siguiente_cursor: null,
        });
      }
      if (url.includes("categoria=tareas")) {
        return Response.json({
          resumen: summary,
          eventos: [event(14, "Tarea creada", "tareas", "/tareas/t1")],
          siguiente_cursor: 12,
        });
      }
      return Response.json({
        resumen: summary,
        eventos: [event(15, "Archivo subido", "archivos")],
        siguiente_cursor: null,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ActivityPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Actividad" })).toBeInTheDocument();
    expect(await screen.findByText("En curso")).toBeInTheDocument();
    expect(screen.getByText("12 completadas")).toBeInTheDocument();
    expect(screen.getByText("Tu decisión")).toBeInTheDocument();
    expect(screen.getByText("75 %")).toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(screen.getByText("Archivo subido")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Tareas" }));
    expect(await screen.findByText("Tarea creada")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Abrir Tarea creada/ })).toHaveAttribute(
      "href",
      "/tareas/t1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Cargar anteriores" }));

    expect(await screen.findByText("Plan aprobado")).toBeInTheDocument();
    expect(screen.getByText("Tarea creada")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Cargar anteriores" })).not.toBeInTheDocument();
    });
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("antes_de=12")),
    ).toBe(true);
  });

  it("explica cómo recuperarse cuando no se puede leer la actividad", async () => {
    const fetchMock = vi.fn(
      async () => Response.json({ error: "sin conexión" }, { status: 503 }),
    );
    vi.stubGlobal(
      "fetch",
      fetchMock,
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ActivityPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("No se pudo leer la actividad. Vuelve a intentarlo."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
