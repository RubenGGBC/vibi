import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EntrevistaModal } from "./EntrevistaModal";
import type { Propuesta } from "../types";

// La entrevista hablada usa la voz del navegador (`speakSpanish`), que no
// existe en jsdom. El camino de voz en sí (grabar, transcribir) se valida a
// mano en el navegador, como ya pasa con `FacePage`; aquí se prueba el
// camino de texto, que es el que sí puede correr en la suite.
vi.mock("../lib/voice", async () => {
  const real = await vi.importActual<typeof import("../lib/voice")>("../lib/voice");
  return {
    ...real,
    supportsVoiceConversation: () => false,
    speakSpanish: (_texto: string, onEnd: () => void) => {
      onEnd();
      return () => undefined;
    },
  };
});

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
      endpoint: "https://mcp.example.test/pdf",
    },
    {
      tipo: "mcp",
      referencia: "notes/notes-mcp",
      titulo: "Gestor de Notas",
      justificacion: "Organiza notas",
      transporte: "local",
      bloque: "encaja",
      endpoint: "",
    },
  ];

  it("completa el flujo de entrevista paso a paso, con la parte de preguntas como conversación", async () => {
    let completado = false;
    let cuerpoCompletar: Record<string, unknown> | null = null;
    let cuerpoPropuesta: Record<string, unknown> | null = null;
    let turnos = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/perfil/entrevista/hipotesis") {
        return Response.json({
          hipotesis: [{ clase: "dominio", valor: "medicina", evidencia: "Carpetas de Bioquimica" }],
          tiene_nodo: true,
        });
      }
      if (url === "/api/perfil/entrevista/turno" && init?.method === "POST") {
        turnos += 1;
        if (turnos === 1) {
          // Primer turno: el historial que manda el cliente está vacío.
          return Response.json({ vibi_dice: "¿Para qué vas a usar Vibi?", terminado: false });
        }
        return Response.json({
          vibi_dice: "Gracias, con esto tengo para buscarte lo que necesitas.",
          terminado: true,
          resumen: {
            afirmaciones: [
              { clase: "preferencia", valor: "Estudia medicina" },
              { clase: "aficion", valor: "Le gustan los videojuegos" },
            ],
            texto_libre: "Estudiar medicina y leer apuntes en PDF; le gustan los videojuegos.",
          },
        });
      }
      if (url === "/api/perfil/entrevista/propuesta" && init?.method === "POST") {
        cuerpoPropuesta = JSON.parse(String(init.body));
        return Response.json(mockPropuestas);
      }
      if (url === "/api/perfil/entrevista/completar" && init?.method === "POST") {
        completado = true;
        cuerpoCompletar = JSON.parse(String(init.body));
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

    // Paso 2: la primera pregunta llega sola, sin que el cliente mande nada
    expect(await screen.findByText("¿Para qué vas a usar Vibi?")).toBeInTheDocument();

    // Respondo por texto — el camino de voz no corre en esta suite.
    await userEvent.type(
      screen.getByRole("textbox", { name: /Responder a Vibi/i }),
      "Estudio medicina y quiero ayuda con mis apuntes",
    );
    await userEvent.click(screen.getByRole("button", { name: /Enviar respuesta/i }));

    // Al cerrar la entrevista, avanza sola a propuestas — no hay botón que pulsar.
    expect(await screen.findByText(/1. Lo que has pedido/i)).toBeInTheDocument();
    expect(screen.getByText(/2. Lo que además encaja/i)).toBeInTheDocument();
    expect(screen.getByText("PDF Assistant")).toBeInTheDocument();
    expect(screen.getByText("Gestor de Notas")).toBeInTheDocument();

    // Lo que se busca sale de lo clasificado "preferencia", no del
    // `texto_libre` entero — así una afición mencionada ahí (aunque se le
    // pidió al modelo que no lo hiciera) no contamina la búsqueda de MCP.
    expect(cuerpoPropuesta).not.toBeNull();
    expect(cuerpoPropuesta!.texto_libre).toBe("Estudia medicina");

    // Avanzar a confirmar
    await userEvent.click(screen.getByRole("button", { name: /Siguiente: Confirmar/i }));

    // Paso 4: Confirmación
    expect(await screen.findByText("Confirmar especialización")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Finalizar y Aplicar/i }));

    await waitFor(() => {
      expect(completado).toBe(true);
      expect(onClose).toHaveBeenCalled();
    });

    // Las afirmaciones del resumen de la conversación llegan a completar().
    const afirmaciones = (
      cuerpoCompletar as unknown as { afirmaciones: Array<{ clase: string; valor: string }> }
    ).afirmaciones;
    expect(afirmaciones).toContainEqual({
      clase: "preferencia",
      valor: "Estudia medicina",
      procedencia: "entrevista",
    });
  });
});
