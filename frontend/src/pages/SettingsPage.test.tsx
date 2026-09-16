import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "./SettingsPage";

const settings = {
  chat_provider: "groq",
  chat_model: "llama-3.3-70b-versatile",
  tools_provider: "anthropic",
  tools_model: "claude-haiku-4-5",
  speech_provider: "groq",
  speech_model: "whisper-large-v3-turbo",
  agent_provider: "anthropic",
  agent_model: "claude-sonnet-5",
  credentials: {
    anthropic: { configured: false, source: "none" },
    groq: { configured: true, source: "system" },
  },
  effective: {
    tools: { provider: "groq", model: "llama-3.3-70b-versatile", available: true, fallback: true },
  },
};

describe("SettingsPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("guarda Haiku y una clave personal sin pedir las claves existentes", async () => {
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
      clear: () => undefined,
    });
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/api/apariencia")) {
        return Response.json({
          color_cara: "#FFFFFF",
          color_antifaz: "#0C0714",
          color_sombrero: "#F4121B",
          actualizada_en: 0,
        });
      }
      if (init?.method === "PUT") return Response.json({ ...settings, effective: { tools: { available: true, fallback: false } } });
      return Response.json(settings);
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SettingsPage />
      </QueryClientProvider>,
    );

    expect(
      (await screen.findAllByDisplayValue("claude-haiku-4-5")).length,
    ).toBeGreaterThan(0);
    const keyInputs = screen.getAllByPlaceholderText("Pegar API key");
    await userEvent.type(keyInputs[0], "sk-ant-personal-test-key");
    await userEvent.click(screen.getByRole("button", { name: "Guardar y aplicar" }));

    expect(await screen.findByText("Configuración aplicada.")).toBeInTheDocument();
    const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    const body = JSON.parse(String(putCall?.[1]?.body));
    expect(body.tools_provider).toBe("anthropic");
    expect(body.tools_model).toBe("claude-haiku-4-5");
    expect(body.anthropic_api_key).toBe("sk-ant-personal-test-key");
    expect(body).not.toHaveProperty("groq_api_key");

    await userEvent.click(screen.getByRole("button", { name: "Usar paleta Verde" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar identidad" }));
    const aparienciaPut = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/api/apariencia") && init?.method === "PUT",
    );
    expect(JSON.parse(String(aparienciaPut?.[1]?.body))).toMatchObject({
      color_cara: "#EFFFF5",
      color_antifaz: "#09251B",
      color_sombrero: "#18C878",
    });
  });
});
