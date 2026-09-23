import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { applyServerEvent } from "../lib/useEvents";
import type { SpeechStream } from "../lib/voice";

const listeners = new Map<string, (event: { payload: unknown }) => void>();
const invoke = vi.fn<(comando: string) => Promise<undefined>>(
  async () => undefined,
);

vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: async (nombre: string, handler: (event: { payload: unknown }) => void) => {
    listeners.set(nombre, handler);
    return () => listeners.delete(nombre);
  },
}));
vi.mock("../lib/useEvents", async (original) => ({
  ...(await original<typeof import("../lib/useEvents")>()),
  useEvents: vi.fn(),
}));
vi.mock("../lib/notifications", () => ({ notificar: vi.fn() }));
vi.mock("./VibiFace", () => ({ VibiFace: () => null }));

// La captura de voz y la locución se sustituyen por dobles observables: lo que
// se quiere comprobar es QUÉ se manda a locutar y CUÁNDO, no cómo suena.
let alSilencio: (() => void) | null = null;
const empujado: { texto: string; boundary: boolean }[] = [];
let terminado = false;

vi.mock("../lib/voice", () => ({
  startVoiceCapture: async (onSilence: () => void) => {
    alSilencio = onSilence;
    return {
      stop: async () => new Blob(["audio"], { type: "audio/webm" }),
      cancel: () => undefined,
    };
  },
  createSpeechStream: (): SpeechStream => ({
    push: (texto: string, options?: { boundary?: boolean }) =>
      empujado.push({ texto, boundary: options?.boundary ?? false }),
    end: () => {
      terminado = true;
    },
    cancel: () => undefined,
  }),
  // Los acuses pregrabados y la locución suelta no participan en lo que aquí se
  // comprueba, pero el componente los llama al montarse: sin dobles, el módulo
  // simulado se queda sin esos exports y el render muere antes de la primera
  // aserción.
  prewarmAcknowledgements: async () => undefined,
  takeAcknowledgement: () => null,
  speakSpanish: (_texto: string, onEnd: () => void) => {
    onEnd();
    return () => undefined;
  },
}));

const { CompanionApp } = await import("./CompanionApp");

const settings = {
  apiBase: "http://127.0.0.1:8000",
  nodeToken: "nodo.secreto",
  nodeName: "Sobremesa",
  userToken: "jwt",
  userName: "ruben",
};

describe("la cara del companion locuta el turno según llega", () => {
  beforeEach(() => {
    listeners.clear();
    empujado.length = 0;
    alSilencio = null;
    terminado = false;
    invoke.mockClear();
    window.localStorage.clear();
    window.localStorage.setItem(
      "vibi.companion.settings",
      JSON.stringify(settings),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("dice el acuse anterior a la herramienta sin esperar al final del turno", async () => {
    let clientRef = "";
    let resolverVoz: (respuesta: unknown) => void = () => undefined;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/voz/abrir")) {
          return Response.json({ conversation_id: "conv-1" });
        }
        if (url.endsWith("/api/voz")) {
          clientRef = String((init?.body as FormData).get("client_ref"));
          return new Promise((resolve) => {
            resolverVoz = (respuesta) => resolve(Response.json(respuesta));
          });
        }
        return Response.json({});
      }),
    );

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <CompanionApp />
      </QueryClientProvider>,
    );

    // Despertar: abre la conversación y se pone a escuchar.
    await act(async () => {
      listeners.get("vibi://wake")?.({ payload: undefined });
    });
    expect(await screen.findByText("Te escucho")).toBeInTheDocument();

    // El silencio cierra el clip y lanza el turno.
    await act(async () => {
      alSilencio?.();
    });
    expect(clientRef).toBeTruthy();

    // Mientras la herramienta trabaja, Vibi ya ha escrito el acuse y el
    // servidor ha cerrado el bloque: eso es justo lo que debe sonar YA, no al
    // final. Esta era la frase que se quedaba muda en el companion.
    await act(async () => {
      applyServerEvent(client, {
        tipo: "chat_runtime",
        event: "delta",
        conversation_id: "conv-1",
        turn_id: clientRef,
        delta: "Ahora te lo busco",
        reset: true,
        boundary: true,
      });
    });

    expect(empujado).toContainEqual({
      texto: "Ahora te lo busco",
      boundary: true,
    });
    expect(terminado).toBe(false);

    // Y el cierre del turno trae solo el bloque posterior a la herramienta.
    await act(async () => {
      resolverVoz({
        via: "herramienta",
        transcripcion: "ponme ese vídeo",
        respuesta: "Listo, te lo he abierto.",
      });
    });

    expect(empujado.at(-1)?.texto).toBe("Listo, te lo he abierto.");
    expect(terminado).toBe(true);
  });

  it("avisa en la cara cuando la consola no tiene sesión", async () => {
    window.localStorage.setItem(
      "vibi.companion.settings",
      JSON.stringify({ ...settings, userToken: undefined }),
    );
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({})));

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <CompanionApp />
      </QueryClientProvider>,
    );

    // Sin esto el companion se quedaba callado para siempre: ni aviso, ni forma
    // de enterarse de que faltaba una credencial. Y no basta con señalarlo: lo
    // que falta es solo el JWT, así que se pide aquí mismo en vez de mandarte a
    // buscar dónde se arregla.
    expect(await screen.findByText("Reconectar la consola")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Reconectar" }),
    ).toBeInTheDocument();
  });
  it("abre el bocadillo con un clic sin despertar la voz", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        urls.push(String(input));
        return Response.json({ ordenes: [] });
      }),
    );

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <CompanionApp />
      </QueryClientProvider>,
    );

    const cara = await screen.findByRole("button", {
      name: "Preguntar a Vibi",
    });
    invoke.mockClear();
    await userEvent.click(cara);

    expect(
      await screen.findByRole("dialog", { name: "Chat con Vibi" }),
    ).toBeInTheDocument();

    // Escribir es justo lo que haces cuando no puedes hablar: si el clic
    // abriera también la sesión de voz, Vibi contestaría en alto delante de
    // quien tengas al lado y el bocadillo no serviría para nada.
    expect(urls.some((url) => url.includes("/api/voz"))).toBe(false);
    expect(alSilencio).toBeNull();
    expect(invoke.mock.calls.map(([nombre]) => nombre)).not.toContain(
      "end_conversation",
    );
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith("set_companion_mode", {
        mode: "chat",
      }),
    );
  });

  it("al cerrar el chat la mascota sigue ahí y se puede volver a abrir", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ordenes: [] })));

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <CompanionApp />
      </QueryClientProvider>,
    );

    const cara = await screen.findByRole("button", {
      name: "Preguntar a Vibi",
    });
    await userEvent.click(cara);
    await screen.findByRole("dialog", { name: "Chat con Vibi" });

    await userEvent.click(
      screen.getByRole("button", { name: "Cerrar el chat" }),
    );

    expect(
      screen.queryByRole("dialog", { name: "Chat con Vibi" }),
    ).not.toBeInTheDocument();
    expect(cara).toBeInTheDocument();

    await userEvent.click(cara);
    expect(
      await screen.findByRole("dialog", { name: "Chat con Vibi" }),
    ).toBeInTheDocument();
  });
  it("el clic principal pregunta y nunca esconde a la mascota", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ordenes: [] })));

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <CompanionApp />
      </QueryClientProvider>,
    );

    const cara = await screen.findByRole("button", {
      name: "Preguntar a Vibi",
    });
    invoke.mockClear();
    await userEvent.click(cara);

    expect(invoke.mock.calls.map(([nombre]) => nombre)).not.toContain(
      "end_conversation",
    );
    expect(
      await screen.findByRole("dialog", { name: "Chat con Vibi" }),
    ).toBeInTheDocument();
  });
});
