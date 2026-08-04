import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

vi.mock("../lib/useEvents", () => ({ useEvents: vi.fn() }));

describe("AppShell", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("expone Skill Studio como espacio principal junto al catálogo de tools", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/yo")) {
          return Response.json({ id: "u1", nombre: "Ana" });
        }
        if (url.endsWith("/api/proyectos")) {
          return Response.json({ proyectos: [] });
        }
        return Response.json([]);
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<p>Consola</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("link", { name: /Skills/ })).toHaveAttribute(
      "href",
      "/skills",
    );
    expect(screen.getByRole("link", { name: /Tools/ })).toHaveAttribute(
      "href",
      "/herramientas",
    );
  });
});
