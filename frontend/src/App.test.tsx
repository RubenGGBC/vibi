import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

vi.mock("./lib/useEvents", () => ({ useEvents: vi.fn() }));
vi.mock("./components/RailFace", () => ({ RailFace: () => <div /> }));
// Sin puerta: lo que se prueba aquí es a dónde llevan las rutas, no quién puede
// entrar por ellas.
vi.mock("./components/ProtectedRoute", () => ({
  ProtectedRoute: () => <Outlet />,
}));

const montar = (ruta: string) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/archivos")) {
        return Response.json({ proyecto: null, archivos: [] });
      }
      if (url.endsWith("/conversaciones")) {
        return Response.json({ proyecto: null, conversaciones: [] });
      }
      if (url.includes("/api/proyectos")) {
        return Response.json({ proyectos: [], detalles: [] });
      }
      if (url.includes("/api/yo")) return Response.json({ id: "u1", nombre: "Ana" });
      if (url.includes("/api/nodos/aprobaciones")) return Response.json({ ordenes: [] });
      if (url.includes("/api/nodos")) return Response.json({ nodos: [] });
      return Response.json([]);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[ruta]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("rutas de proyectos", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sirve Proyectos en su ruta de primer nivel", async () => {
    montar("/proyectos");
    expect(
      await screen.findByRole("heading", { name: "Proyectos", level: 1 }),
    ).toBeInTheDocument();
  });

  it("las URLs viejas del taller siguen llevando a Proyectos", async () => {
    // Proyectos salió del taller al rail; un enlace guardado a la ruta de
    // dentro no puede quedarse en un 404 silencioso.
    montar("/taller/proyectos");
    expect(
      await screen.findByRole("heading", { name: "Proyectos", level: 1 }),
    ).toBeInTheDocument();
  });

  it("el redirect del taller conserva el id del proyecto", async () => {
    montar("/taller/proyectos/p1");
    // La prueba de que el id sobrevivió al redirect es a quién le pregunta la
    // pantalla: si se hubiera perdido, acabaría en el listado y no pediría esto.
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/proyectos/p1/archivos",
        expect.anything(),
      );
    });
  });
});
