import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectsPage } from "./ProjectsPage";
import type { Project } from "../types";

const proyecto = (nombre: string, id: string): Project => ({
  id,
  nombre,
  slug: nombre,
  descripcion: "",
  archivos: 2,
  conversaciones: 1,
  carpeta: true,
  created_at: 1,
  updated_at: 1,
});

const montar = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProjectsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("ProjectsPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("confirma y elimina un proyecto desde su tarjeta", async () => {
    let detalles = [proyecto("vibi", "p1")];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/proyectos/p1" && init?.method === "DELETE") {
        detalles = [];
        return new Response(null, { status: 204 });
      }
      if (url === "/api/proyectos") {
        return Response.json({
          proyectos: detalles.map((item) => item.slug),
          detalles,
        });
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn(() => true));
    montar();

    await userEvent.click(
      await screen.findByRole("button", { name: "Eliminar proyecto vibi" }),
    );

    // Borrar el proyecto es cerrar el cajón: lo que había dentro no se pierde,
    // y el aviso tiene que decirlo antes de que lo confirmen.
    expect(window.confirm).toHaveBeenCalledWith(
      "¿Eliminar el proyecto vibi? Se borrará su carpeta; los archivos subidos y las conversaciones guardadas se quedan sueltos en tu espacio.",
    );
    expect(await screen.findByText("vibi se ha eliminado.")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "Eliminar proyecto vibi" }),
      ).not.toBeInTheDocument();
    });
  });

  it("crea un proyecto vacío y lo muestra en el listado", async () => {
    let detalles: Project[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/proyectos" && init?.method === "POST") {
        const creado = proyecto("Tesis", "p2");
        detalles = [{ ...creado, archivos: 0, conversaciones: 0 }];
        return Response.json(detalles[0], { status: 201 });
      }
      if (url === "/api/proyectos") {
        return Response.json({
          proyectos: detalles.map((item) => item.slug),
          detalles,
        });
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);
    montar();

    await userEvent.click(
      await screen.findByRole("button", { name: /Nuevo proyecto/ }),
    );
    await userEvent.type(screen.getByLabelText("Nombre"), "Tesis");
    await userEvent.click(screen.getByRole("button", { name: "Crear proyecto" }));

    expect(await screen.findByText("Tesis está listo.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Tesis" })).toBeInTheDocument();
  });

  it("enlaza cada proyecto con su espacio", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({ proyectos: ["vibi"], detalles: [proyecto("vibi", "p1")] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    montar();

    const enlace = await screen.findByRole("link", { name: /vibi/ });
    expect(enlace).toHaveAttribute("href", "/proyectos/p1");
  });
});
