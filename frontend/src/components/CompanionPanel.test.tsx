import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CompanionPanel } from "./CompanionPanel";
import { loadCompanionSettings } from "../lib/companionApi";

vi.mock("../lib/useEvents", () => ({ useEvents: vi.fn() }));

const settings = {
  apiBase: "http://127.0.0.1:8000",
  nodeToken: "nodo.secreto",
  nodeName: "Sobremesa",
};

/** Un servidor de mentira que contesta lo que toca según la ruta. */
const servidor = (login: unknown = { token: "jwt.nuevo" }) =>
  vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/auth/login")) return Response.json(login);
    if (url.includes("/api/nodos/aprobaciones")) {
      return Response.json({ ordenes: [] });
    }
    if (url.includes("/api/tareas")) return Response.json([]);
    if (url.includes("/api/archivos")) return Response.json({ archivos: [] });
    return Response.json({});
  });

const pintar = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <CompanionPanel />
    </QueryClientProvider>,
  );
};

describe("la consola del companion", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("pide la contraseña en vez de enseñar secciones vacías", async () => {
    // Vinculado antes de que la consola existiera: tiene voz, no tiene sesión.
    window.localStorage.setItem(
      "morgana.companion.settings",
      JSON.stringify(settings),
    );
    const fetchMock = servidor();
    vi.stubGlobal("fetch", fetchMock);

    pintar();

    expect(await screen.findByText("Conecta la consola")).toBeInTheDocument();
    // Y no se ha pedido nada a la API: sin credencial no hay nada que consultar.
    expect(fetchMock).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText("Nombre"), "ruben");
    await userEvent.type(screen.getByLabelText("Contraseña"), "correcta");
    await userEvent.click(screen.getByRole("button", { name: "Conectar" }));

    expect(await screen.findByRole("button", { name: /Permisos/ })).toBeInTheDocument();
    expect(loadCompanionSettings()?.userToken).toBe("jwt.nuevo");
  });

  it("vuelve a pedirla cuando el JWT caduca en mitad de la sesión", async () => {
    window.localStorage.setItem(
      "morgana.companion.settings",
      JSON.stringify({ ...settings, userToken: "jwt.caducado" }),
    );
    vi.stubGlobal("fetch", servidor());

    pintar();
    expect(await screen.findByRole("button", { name: /Permisos/ })).toBeInTheDocument();

    // El cliente HTTP compartido avisa así de un 401.
    window.dispatchEvent(new CustomEvent("morgana:unauthorized"));

    expect(await screen.findByText("Conecta la consola")).toBeInTheDocument();
    // El token muerto no puede quedarse guardado: al arrancar volvería a
    // instalarse y el 401 se repetiría en cada sesión sin explicación.
    expect(loadCompanionSettings()?.userToken).toBeUndefined();
    expect(loadCompanionSettings()?.nodeToken).toBe("nodo.secreto");
  });
});
