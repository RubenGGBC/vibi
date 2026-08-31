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
      paquete: "",
    },
    {
      tipo: "mcp",
      referencia: "notes/notes-mcp",
      titulo: "Gestor de Notas",
      justificacion: "Organiza notas",
      transporte: "local",
      bloque: "encaja",
      endpoint: "",
      paquete: "npm:notes-mcp@1.0.0",
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

  it("enseña el motivo cuando el servidor rechaza la confirmación", async () => {
    // Pasó en vivo el 30/08/2026: nueve intentos contra un 422, y la pantalla
    // solo decía «revisa la selección». El motivo viaja en la respuesta desde
    // el primer intento; tirarlo es lo que convierte un fallo con explicación
    // en un botón que «no funciona».
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/perfil/entrevista/hipotesis") {
        return Response.json({ hipotesis: [], tiene_nodo: false });
      }
      if (url === "/api/perfil/entrevista/turno" && init?.method === "POST") {
        return Response.json({
          vibi_dice: "Listo.",
          terminado: true,
          resumen: {
            afirmaciones: [{ clase: "preferencia", valor: "Estudia medicina" }],
            texto_libre: "Estudia medicina",
          },
        });
      }
      if (url === "/api/perfil/entrevista/propuesta" && init?.method === "POST") {
        return Response.json(mockPropuestas);
      }
      if (url === "/api/perfil/entrevista/completar" && init?.method === "POST") {
        return Response.json(
          { detail: "El MCP remoto «notes/notes-mcp» necesita un endpoint HTTP válido" },
          { status: 422 },
        );
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <EntrevistaModal onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    // El primer turno ya viene cerrado, así que la conversación pasa sola a
    // propuestas sin pedir ninguna respuesta.
    await userEvent.click(await screen.findByRole("button", { name: /Siguiente: Preguntas/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Siguiente: Confirmar/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Finalizar y Aplicar/i }));

    expect(await screen.findByText(/necesita un endpoint HTTP válido/i)).toBeInTheDocument();
  });

  it("avisa de que un servidor local se instala en la máquina", async () => {
    // Los locales entran desde el 30/08/2026. La diferencia con un remoto no
    // es un detalle técnico: uno se lleva datos fuera y el otro ejecuta código
    // de un tercero aquí dentro, y quien aprueba tiene que verlo.
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/perfil/entrevista/hipotesis") {
        return Response.json({ hipotesis: [], tiene_nodo: false });
      }
      if (url === "/api/perfil/entrevista/turno" && init?.method === "POST") {
        return Response.json({
          vibi_dice: "Listo.",
          terminado: true,
          resumen: {
            afirmaciones: [{ clase: "preferencia", valor: "Estudia medicina" }],
            texto_libre: "Estudia medicina",
          },
        });
      }
      if (url === "/api/perfil/entrevista/propuesta" && init?.method === "POST") {
        return Response.json(mockPropuestas);
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <EntrevistaModal onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: /Siguiente: Preguntas/i }));

    expect(await screen.findByText("Gestor de Notas")).toBeInTheDocument();
    expect(screen.getByText(/se instala y se ejecuta en tu ordenador/i)).toBeInTheDocument();
  });

  it("cuenta lo que se quedó fuera en vez de cerrarse sin decir nada", async () => {
    // Desde el 31/08/2026 una propuesta rota ya no tumba la entrevista: se
    // aparta y lo demás entra. Pero apartarla en silencio sería peor que el
    // error: el usuario había marcado ese servidor y lo vería desaparecer.
    const onClose = vi.fn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/perfil/entrevista/hipotesis") {
        return Response.json({ hipotesis: [], tiene_nodo: false });
      }
      if (url === "/api/perfil/entrevista/turno" && init?.method === "POST") {
        return Response.json({
          vibi_dice: "Listo.",
          terminado: true,
          resumen: {
            afirmaciones: [{ clase: "preferencia", valor: "Estudia medicina" }],
            texto_libre: "Estudia medicina",
          },
        });
      }
      if (url === "/api/perfil/entrevista/propuesta" && init?.method === "POST") {
        return Response.json(mockPropuestas);
      }
      if (url === "/api/perfil/entrevista/completar" && init?.method === "POST") {
        return Response.json({
          afirmaciones: [],
          capacidades: [],
          descartes: [
            {
              que: "capacidad",
              referencia: "com.green-api/whatsapp",
              motivo: "es remoto y llegó sin un endpoint HTTP válido",
            },
          ],
        });
      }
      return Response.json({ error: "No esperado" }, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <EntrevistaModal onClose={onClose} />
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByRole("button", { name: /Siguiente: Preguntas/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Siguiente: Confirmar/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Finalizar y Aplicar/i }));

    expect(await screen.findByText(/com.green-api\/whatsapp/)).toBeInTheDocument();
    expect(screen.getByText(/sin un endpoint HTTP válido/i)).toBeInTheDocument();
    // El perfil se aplicó: no se cierra a la fuerza, se deja leer el aviso.
    expect(onClose).not.toHaveBeenCalled();
  });
});
