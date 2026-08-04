import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "./api";
import { clearToken, getToken, setToken } from "./auth";


describe("apiFetch", () => {
  afterEach(() => {
    clearToken();
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it("inyecta el bearer guardado", async () => {
    setToken("jwt-test");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ nombre: "ruben" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/yo");

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(request.headers).get("Authorization")).toBe(
      "Bearer jwt-test",
    );
  });

  it("borra la sesión y vuelve a login ante 401", async () => {
    setToken("caducado");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "Token inválido" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch("/api/yo")).rejects.toBeInstanceOf(ApiError);

    expect(getToken()).toBeNull();
    expect(window.location.pathname).toBe("/login");
  });

  it("expone el mensaje JSON de los errores", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "Proyecto no encontrado" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch("/api/mensaje")).rejects.toMatchObject({
      status: 400,
      message: "Proyecto no encontrado",
    });
  });

  it("expone el detalle estándar de FastAPI", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Argumentos inválidos" }), {
          status: 422,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch("/api/herramientas/tasks.list/ejecutar")).rejects.toMatchObject({
      status: 422,
      message: "Argumentos inválidos",
    });
  });
});
