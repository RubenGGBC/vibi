import { afterEach, describe, expect, it, vi } from "vitest";

import {
  closeCompanionConversation,
  CompanionApiError,
  type CompanionSettings,
} from "./companionApi";

const settings: CompanionSettings = {
  apiBase: "http://127.0.0.1:8000",
  nodeToken: "nodo.secreto",
  nodeName: "Sobremesa",
};

describe("closeCompanionConversation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("pide al servidor archivar la conversación con el token del nodo", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await closeCompanionConversation(settings);

    const [url, request] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8000/api/voz/cerrar");
    expect(request.method).toBe("POST");
    expect(new Headers(request.headers).get("Authorization")).toBe(
      "Bearer nodo.secreto",
    );
  });

  it("propaga el fallo para que la cara no lo dé por hecho", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Token inválido" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(closeCompanionConversation(settings)).rejects.toBeInstanceOf(
      CompanionApiError,
    );
  });
});
