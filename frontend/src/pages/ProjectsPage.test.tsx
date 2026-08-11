import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectsPage } from "./ProjectsPage";

describe("ProjectsPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("confirma y elimina un proyecto desde su tarjeta", async () => {
    let projects = ["vibi"];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/proyectos/vibi" && init?.method === "DELETE") {
        projects = [];
        return new Response(null, { status: 204 });
      }
      if (url === "/api/proyectos") {
        return Response.json({ proyectos: projects });
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn(() => true));
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <ProjectsPage />
      </QueryClientProvider>,
    );

    await userEvent.click(
      await screen.findByRole("button", { name: "Eliminar proyecto vibi" }),
    );

    expect(window.confirm).toHaveBeenCalledWith(
      "¿Eliminar el proyecto vibi? Se borrarán permanentemente todos sus archivos.",
    );
    expect(await screen.findByText("vibi se ha eliminado.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Eliminar proyecto vibi" })).not.toBeInTheDocument();
    });
  });
});
