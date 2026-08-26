import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EntrevistaModal } from "./EntrevistaModal";
import type { Propuesta } from "../types";

describe("EntrevistaModal", () => {
  afterEach(() => vi.unstubAllGlobals());

  const mockPropuestas: Propuesta[] = [
    {
      tipo: "mcp",
      referencia: "ai.pdfassistant/pdfassistant",
      titulo: "PDF Assistant",
      justificacion: "Lee y resume PDFs",
      transporte: "remoto",
      bloque: "pedido",
    },
    {
      tipo: "mcp",
      referencia: "notes/notes-mcp",
      titulo: "Gestor de Notas",
      justificacion: "Organiza notas",
      transporte: "local",
      bloque: "encaja",
    },
  ];

  it("completa el flujo de entrevista paso a paso con bloques pedido y encaja", async () => {
    let completado = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/perfil/entrevista/hipotesis") {
        return Response.json({
          hipotesis: [{ clase: "dominio", valor: "medicina", evidencia: "Carpetas de Bioquimica" }],
          tiene_nodo: true,
        });
      }
      if (url === "/api/perfil/entrevista/propuesta" && init?.method === "POST") {
        return Response.json(mockPropuestas);
      }
      if (url === "/api/perfil/entrevista/completar" && init?.method === "POST") {
        completado = true;
        return Response.json({ ok: true });
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const onClose = vi.fn();

    render(
      <QueryClientProvider client={client}>
        <EntrevistaModal onClose={onClose} />
      </QueryClientProvider>,
    );

    // Paso 1: Evidencia
    expect(await screen.findByText("medicina")).toBeInTheDocument();
    expect(screen.getByText(/Carpetas de Bioquimica/i)).toBeInTheDocument();

    // Avanzar a preguntas
    await userEvent.click(screen.getByRole("button", { name: /Siguiente: Preguntas/i }));

    // Paso 2: Preguntas
    expect(await screen.findByText("Cuatro preguntas para afinar a Vibi")).toBeInTheDocument();
    const textareas = screen.getAllByRole("textbox");
    await userEvent.type(textareas[0], "Estudiar medicina");
    await userEvent.type(textareas[1], "Que sea rapida");
    await userEvent.type(textareas[2], "Leer apuntes pdf");
    await userEvent.type(textareas[3], "Toco la guitarra");

    // Avanzar a propuestas
    await userEvent.click(screen.getByRole("button", { name: /Siguiente: Ver propuestas/i }));

    // Paso 3: Propuestas en dos bloques
    expect(await screen.findByText(/1. Lo que has pedido/i)).toBeInTheDocument();
    expect(screen.getByText(/2. Lo que además encaja/i)).toBeInTheDocument();
    expect(screen.getByText("PDF Assistant")).toBeInTheDocument();
    expect(screen.getByText("Gestor de Notas")).toBeInTheDocument();

    // Avanzar a confirmar
    await userEvent.click(screen.getByRole("button", { name: /Siguiente: Confirmar/i }));

    // Paso 4: Confirmación
    expect(await screen.findByText("Confirmar especialización")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Finalizar y Aplicar/i }));

    await waitFor(() => {
      expect(completado).toBe(true);
      expect(onClose).toHaveBeenCalled();
    });
  });
});
