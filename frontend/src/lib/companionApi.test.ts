import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getToken } from "./auth";
import {
  clearCompanionSettings,
  closeCompanionConversation,
  CompanionApiError,
  connectCompanionConsole,
  forgetCompanionUserToken,
  loadCompanionSettings,
  saveCompanionSettings,
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

describe("la sesión de la consola", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("migra los ajustes guardados por la aplicación anterior", () => {
    window.localStorage.setItem(
      "morgana.companion.settings",
      JSON.stringify(settings),
    );

    expect(loadCompanionSettings()).toEqual(settings);
    expect(window.localStorage.getItem("vibi.companion.settings")).toBe(
      JSON.stringify(settings),
    );
  });

  it("no resucita los ajustes anteriores después de desvincular", () => {
    window.localStorage.setItem(
      "morgana.companion.settings",
      JSON.stringify(settings),
    );
    expect(loadCompanionSettings()).toEqual(settings);

    clearCompanionSettings();

    expect(loadCompanionSettings()).toBeNull();
    expect(window.localStorage.getItem("morgana.companion.settings")).toBeNull();
    expect(window.localStorage.getItem("vibi.companion.settings")).toBeNull();
  });

  it("consigue el JWT sin tocar la vinculación de voz", async () => {
    // Un companion de antes de que la consola existiera: habla, pero nunca
    // llegó a pedir credencial de usuario.
    saveCompanionSettings(settings);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ token: "jwt.nuevo" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await connectCompanionConsole({ name: "ruben", password: "correcta" });

    const guardado = loadCompanionSettings();
    expect(guardado?.userToken).toBe("jwt.nuevo");
    expect(guardado?.userName).toBe("ruben");
    // Lo que ya funcionaba tiene que seguir intacto.
    expect(guardado?.nodeToken).toBe("nodo.secreto");
    expect(guardado?.apiBase).toBe("http://127.0.0.1:8000");
    // Y el cliente HTTP compartido ya sabe con qué hablar.
    expect(getToken()).toBe("jwt.nuevo");
  });

  it("al caducar olvida solo el JWT, no el nodo", () => {
    saveCompanionSettings({ ...settings, userToken: "jwt.viejo", userName: "ruben" });

    forgetCompanionUserToken();

    const guardado = loadCompanionSettings();
    expect(guardado?.userToken).toBeUndefined();
    expect(getToken()).toBeNull();
    // Si se perdiera esto, el próximo despertar pediría vincular el PC entero.
    expect(guardado?.nodeToken).toBe("nodo.secreto");
    expect(guardado?.userName).toBe("ruben");
  });
});
