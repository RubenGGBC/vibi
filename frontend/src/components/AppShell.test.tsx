import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

vi.mock("../lib/useEvents", () => ({ useEvents: vi.fn() }));
// La cara monta una escena SVG con su bucle de dibujo, y eso no es lo que se
// prueba aquí. Que esté anclada en el rail sí, y para eso basta el hueco.
vi.mock("./RailFace", () => ({ RailFace: () => <div data-testid="rail-cara" /> }));

const montar = (respuestas: Record<string, unknown> = {}) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      for (const [trozo, cuerpo] of Object.entries(respuestas)) {
        if (url.includes(trozo)) return Response.json(cuerpo);
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
      <MemoryRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<p>Ahora</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("AppShell", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("nombra lo que haces, no el tipo de objeto que hay dentro", async () => {
    montar();
    const rail = await screen.findByRole("navigation", { name: "Vibi" });
    const destinos = within(rail).getAllByRole("link").map((a) => a.textContent);
    expect(destinos).toEqual([
      "Proyectos",
      "Ahora",
      "Hilo",
      "Encargos",
      "Equipos",
      "Taller",
    ]);
  });

  it("pone Proyectos el primero y fuera del taller", async () => {
    // Dentro de un proyecto están sus archivos, sus conversaciones guardadas y
    // la carpeta que recibe sus encargos: dejarlo en el cajón de lo que se toca
    // de vez en cuando era del tiempo en que solo listaba repos clonados.
    montar();
    const rail = await screen.findByRole("navigation", { name: "Vibi" });
    const primero = within(rail).getAllByRole("link")[0];
    expect(primero).toHaveTextContent("Proyectos");
    expect(primero).toHaveAttribute("href", "/proyectos");
  });

  it("saca la configuración del agente del camino diario", async () => {
    // Skills y Tools gastaban dos de los seis huecos del rail siendo cosas que
    // se tocan de higos a brevas. Siguen a un clic, dentro del taller.
    montar();
    const taller = await screen.findByRole("link", { name: "Taller" });
    expect(taller).toHaveAttribute("href", "/taller");
    expect(screen.queryByRole("link", { name: "Skills" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Tools" })).toBeNull();
  });

  it("ancla la cara en el rail, no en una de las páginas", async () => {
    // Es lo que sostiene la dirección C: la consola y la ventana flotante son
    // la misma cosa en dos tallas porque las dos enseñan la misma cara.
    montar();
    expect(await screen.findByTestId("rail-cara")).toBeInTheDocument();
  });

  it("presenta la consola como la aplicación local de Vibi", async () => {
    montar();

    expect(await screen.findByText("VIBI // LOCAL")).toBeInTheDocument();
    expect(screen.getByText("SISTEMA EN LÍNEA")).toBeInTheDocument();
  });

  it("cuenta los encargos vivos y los equipos conectados sin entrar a mirar", async () => {
    montar({
      "/api/tareas": [
        { id: "t1", estado: "ejecutando" },
        { id: "t2", estado: "pendiente" },
        { id: "t3", estado: "completada" },
      ],
      "/api/nodos/aprobaciones": { ordenes: [] },
      "/api/nodos": {
        nodos: [
          { id: "n1", nombre: "Sobremesa", conectado: true, last_seen: 0 },
          { id: "n2", nombre: "Servidor", conectado: false, last_seen: 0 },
        ],
      },
    });
    // Dos vivas de tres: la completada ya no espera nada de ti.
    expect(await screen.findByText("2")).toBeInTheDocument();
    expect(await screen.findByText("1/2")).toBeInTheDocument();
  });

  it("saca el permiso pendiente al rail, donde se ve desde cualquier página", async () => {
    montar({
      "/api/nodos/aprobaciones": {
        ordenes: [{ id: "o1", capability: "shell.run", riesgo: "alto" }],
      },
    });
    expect(
      await screen.findByText("1 orden espera tu permiso"),
    ).toBeInTheDocument();
  });
});
