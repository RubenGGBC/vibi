import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectDetailPage } from "./ProjectDetailPage";
import type { Project, SavedConversation, UserFile } from "../types";

const proyecto: Project = {
  id: "p1",
  nombre: "Tesis",
  slug: "Tesis",
  descripcion: "todo lo del TFG",
  archivos: 1,
  conversaciones: 1,
  carpeta: true,
  created_at: 1,
  updated_at: 1,
};

const archivo: UserFile = {
  id: "f1",
  name: "capitulo-3.md",
  source: "managed",
  project_id: "p1",
  relative_path: null,
  media_type: "text/markdown",
  size_bytes: 2048,
  modified_at: 1,
  created_at: 1,
  download_url: "/api/archivos/f1/contenido",
};

const conversacion: SavedConversation = {
  id: "c1",
  titulo: "Estructura del capítulo 3",
  estado: "archivada",
  project_id: "p1",
  mensajes: 12,
  created_at: 1,
  updated_at: 1,
};

const montar = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/taller/proyectos/p1"]}>
        <Routes>
          <Route path="/taller/proyectos/:id" element={<ProjectDetailPage />} />
          <Route path="/hilo" element={<p>Hilo abierto</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("ProjectDetailPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("enseña juntos los archivos y las conversaciones del proyecto", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/proyectos/p1/archivos") {
          return Response.json({ proyecto, archivos: [archivo] });
        }
        if (url === "/api/proyectos/p1/conversaciones") {
          return Response.json({ proyecto, conversaciones: [conversacion] });
        }
        return Response.json({ error: "No esperado" }, { status: 500 });
      }),
    );
    montar();

    expect(await screen.findByRole("heading", { name: "Tesis" })).toBeInTheDocument();
    expect(await screen.findByText("capitulo-3.md")).toBeInTheDocument();
    expect(
      await screen.findByText("Estructura del capítulo 3"),
    ).toBeInTheDocument();
    expect(screen.getByText(/12 mensajes/)).toBeInTheDocument();
  });

  it("retoma una conversación guardada y lleva al hilo", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/conversaciones/c1/reanudar" && init?.method === "POST") {
        return Response.json({
          conversation_id: "c1",
          conversation_created_at: 1,
          conversation_changed: true,
          thinking_enabled: false,
          messages: [],
        });
      }
      if (url === "/api/proyectos/p1/archivos") {
        return Response.json({ proyecto, archivos: [] });
      }
      if (url === "/api/proyectos/p1/conversaciones") {
        return Response.json({ proyecto, conversaciones: [conversacion] });
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);
    montar();

    await userEvent.click(await screen.findByRole("button", { name: /Retomar/ }));

    expect(await screen.findByText("Hilo abierto")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/conversaciones/c1/reanudar",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("saca un archivo del proyecto diciendo que no lo borra", async () => {
    let archivos = [archivo];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/proyectos/p1/archivos/f1" && init?.method === "DELETE") {
        archivos = [];
        return new Response(null, { status: 204 });
      }
      if (url === "/api/proyectos/p1/archivos") {
        return Response.json({ proyecto, archivos });
      }
      if (url === "/api/proyectos/p1/conversaciones") {
        return Response.json({ proyecto, conversaciones: [] });
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);
    montar();

    await userEvent.click(
      await screen.findByRole("button", { name: "Sacar capitulo-3.md del proyecto" }),
    );

    expect(
      await screen.findByText(
        "El archivo sale del proyecto, pero sigue en tus archivos.",
      ),
    ).toBeInTheDocument();
  });
});
