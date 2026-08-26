import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PerfilPage } from "./PerfilPage";
import type { PerfilUsuario } from "../types";

describe("PerfilPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  const mockPerfil: PerfilUsuario = {
    user_id: "u123",
    resumen: "Se dedica a: medicina y farmacología.",
    afirmaciones: [
      {
        id: 1,
        user_id: "u123",
        clase: "dominio",
        valor: "medicina",
        procedencia: "entrevista",
        confianza: 0.6,
        apoyos: 2,
        contras: 0,
        creada_en: 1000,
        movida_en: 1000,
      },
      {
        id: 2,
        user_id: "u123",
        clase: "herramienta",
        valor: "pdf",
        procedencia: "inventario",
        confianza: 0.4,
        apoyos: 0,
        contras: 0,
        creada_en: 1000,
        movida_en: 1000,
      },
    ],
    capacidades: [
      {
        id: 10,
        user_id: "u123",
        tipo: "mcp",
        referencia: "ai.pdfassistant/pdfassistant",
        justificacion: "Lector y extractor de PDF",
        transporte: "remoto",
        nivel: "completo",
        aprobada_en: 1000,
        usos: 5,
        ultimo_uso: 1500,
      },
    ],
    metricas: {
      tasa_de_aceptacion: 0.85,
      supervivencia_14dias: 1.0,
      total_afirmaciones: 2,
      total_capacidades: 1,
    },
  };

  it("renderiza resumen, métricas, afirmaciones y capacidades", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/perfil") {
        return Response.json(mockPerfil);
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <PerfilPage />
      </QueryClientProvider>,
    );

    // Header y resumen
    expect(await screen.findByText("Se dedica a: medicina y farmacología.")).toBeInTheDocument();
    expect(screen.getByText("Perfil de usuario")).toBeInTheDocument();

    // KPIs
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();

    // Afirmaciones
    expect(screen.getByText("medicina")).toBeInTheDocument();
    expect(screen.getByText("pdf")).toBeInTheDocument();

    // Capacidades
    expect(screen.getByText("ai.pdfassistant/pdfassistant")).toBeInTheDocument();
    expect(screen.getByText("Lector y extractor de PDF")).toBeInTheDocument();
  });

  it("permite añadir una afirmación manual", async () => {
    let afirmaciones = [...mockPerfil.afirmaciones];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/perfil") {
        return Response.json({ ...mockPerfil, afirmaciones });
      }
      if (url === "/api/perfil/afirmaciones" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        const nueva = {
          id: 3,
          user_id: "u123",
          clase: body.clase,
          valor: body.valor,
          procedencia: "entrevista" as const,
          confianza: 0.6,
          apoyos: 0,
          contras: 0,
          creada_en: 2000,
          movida_en: 2000,
        };
        afirmaciones.push(nueva);
        return Response.json(nueva);
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <PerfilPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("medicina")).toBeInTheDocument();

    // Abrir formulario
    await userEvent.click(screen.getByRole("button", { name: /Añadir/i }));

    const input = screen.getByPlaceholderText(/Valor o descripción/i);
    await userEvent.type(input, "cardiologia");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() => {
      expect(screen.getByText("cardiologia")).toBeInTheDocument();
    });
  });

  it("permite abrir el modal de entrevista de especialización", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/perfil") {
        return Response.json(mockPerfil);
      }
      if (url === "/api/perfil/entrevista/hipotesis") {
        return Response.json({ hipotesis: [], tiene_nodo: false });
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <PerfilPage />
      </QueryClientProvider>,
    );

    await userEvent.click(
      await screen.findByRole("button", { name: /Entrevista de especialización/i }),
    );

    expect(await screen.findByText("Escaneo silencioso del entorno")).toBeInTheDocument();
    expect(screen.getByText("1. Entorno")).toBeInTheDocument();
  });
});
