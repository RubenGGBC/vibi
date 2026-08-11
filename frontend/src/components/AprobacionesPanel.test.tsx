import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AprobacionesPanel } from "./AprobacionesPanel";
import { applyServerEvent } from "../lib/useEvents";
import type { NodeOrder } from "../types";

const orden: NodeOrder = {
  id: "orden-1",
  node_id: "nodo-1",
  node_nombre: "Servidor Windows",
  capability: "browser.open",
  arguments: { url: "https://www.youtube.com/watch?v=abcdefghijk" },
  estado: "pendiente",
  aprobacion: "pendiente",
  riesgo: "medio",
  motivo: "En este turno Vibi ha leído una búsqueda web.",
  created_at: 0,
  expires_at: Number.MAX_SAFE_INTEGER,
};

describe("AprobacionesPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("saca la tarjeta en cuanto el servidor avisa, aunque llegue con una consulta en vuelo", async () => {
    // La primera consulta sale antes de que la orden exista y volvería vacía:
    // si su respuesta pisara lo que trae el evento, la tarjeta desaparecería
    // sin que nadie hubiera decidido nada.
    let vacias = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        vacias += 1;
        return Response.json({ ordenes: vacias === 1 ? [] : [orden] });
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <AprobacionesPanel />
      </QueryClientProvider>,
    );

    // Vibi quiere abrir un vídeo y el contexto viene contaminado.
    await act(async () => {
      applyServerEvent(client, { tipo: "nodo_orden_aprobacion", orden });
    });

    expect(
      await screen.findByText("Vibi quiere hacer algo en otro dispositivo"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("https://www.youtube.com/watch?v=abcdefghijk"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ejecutar" })).toBeInTheDocument();
  });

  it("recupera lo que quedó pendiente mientras no mirabas", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ ordenes: [orden] })),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <AprobacionesPanel />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("Vibi quiere hacer algo en otro dispositivo"),
    ).toBeInTheDocument();
  });
});
