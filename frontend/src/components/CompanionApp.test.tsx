import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { applyServerEvent } from "../lib/useEvents";
import type { SpeechStream } from "../lib/voice";

const listeners = new Map<string, (event: { payload: unknown }) => void>();
const invoke = vi.fn(async () => undefined);

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

    // Sin esto el companion se quedaba callado para siempre: ni pip, ni aviso,
    // ni forma de enterarse de que faltaba una credencial.
    const boton = await screen.findByRole("button", { name: /Consola/ });
    expect(boton).toHaveAttribute(
      "title",
      "Falta conectar la consola: ábrela para hacerlo",
    );
  });
});
