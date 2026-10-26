import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SkillsPage } from "./SkillsPage";

const tool = {
  id: "files.read",
  name: "Leer uno de mis archivos",
  description: "Localiza un archivo propio y extrae su texto.",
  scope: "system",
  primitive_id: "files.read",
  permissions: ["files:read:self"],
  effects: ["filesystem:read"],
  input_schema: {},
  enabled: true,
  source: "builtin",
  created_at: null,
};

const quality = { ready: true, score: 100, issues: [] };

const skill = (enabled = false) => ({
  id: "skill-1",
  slug: "preparar-informe",
  name: "Preparar informe",
  description: "Convierte documentos administrativos en un informe accionable.",
  instructions:
    "Resume los hechos, separa los riesgos y termina con tres acciones concretas.",
  examples: ["Prepara el informe semanal del laboratorio"],
  tool_ids: ["files.read"],
  tools: [tool],
  scope: "personal",
  enabled,
  version: 1,
  quality,
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
});

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SkillsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SkillsPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("crea un manifiesto y lo activa desde el workbench", async () => {
    let stored: ReturnType<typeof skill>[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/skills") && init?.method === "POST") {
        stored = [skill(false)];
        return Response.json(stored[0], { status: 201 });
      }
      if (url.endsWith("/estado") && init?.method === "POST") {
        stored = [skill(true)];
        return Response.json(stored[0]);
      }
      return Response.json({
        skills: stored,
        summary: {
          active: stored.filter((item) => item.enabled).length,
          drafts: stored.filter((item) => !item.enabled).length,
        },
        available_tools: [tool],
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Nueva skill" }));
    await userEvent.type(screen.getByLabelText("Nombre"), "Preparar informe");
    await userEvent.type(
      screen.getByLabelText("Descripción"),
      "Convierte documentos administrativos en un informe accionable.",
    );
    await userEvent.type(
      screen.getByLabelText("Instrucciones"),
      "Resume los hechos, separa los riesgos y termina con tres acciones concretas.",
    );
    await userEvent.type(
      screen.getByLabelText("Ejemplos"),
      "Prepara el informe semanal del laboratorio",
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: /Leer uno de mis archivos/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Guardar borrador" }));

    expect(await screen.findByText("/skill preparar-informe")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Activar Preparar informe" }),
    );
    expect(await screen.findByText("Activa")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/skills/skill-1/estado"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("prueba la skill y previsualiza su exportación portable", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/probar") && init?.method === "POST") {
        return Response.json({
          response: "El informe destaca dos riesgos y tres acciones.",
          skill_id: "skill-1",
          skill_version: 1,
          tool_runs: [{ tool_id: "files.read", status: "succeeded", result: {} }],
          artifacts: [],
        });
      }
      if (url.endsWith("/exportar")) {
        return Response.json({
          filename: "preparar-informe.SKILL.md",
          content: "---\nname: preparar-informe\n---\n\n# Preparar informe",
        });
      }
      return Response.json({
        skills: [skill(true)],
        summary: { active: 1, drafts: 0 },
        available_tools: [tool],
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Probar Preparar informe" }),
    );
    await userEvent.type(
      screen.getByLabelText("Petición de prueba"),
      "Prepara mi informe",
    );
    await userEvent.click(screen.getByRole("button", { name: "Ejecutar prueba" }));
    expect(
      await screen.findByText("El informe destaca dos riesgos y tres acciones."),
    ).toBeInTheDocument();
    expect(screen.getByText("files.read · succeeded")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Exportar Preparar informe" }),
    );
    expect(await screen.findByText("preparar-informe.SKILL.md")).toBeInTheDocument();
    expect(screen.getByText(/name: preparar-informe/)).toBeInTheDocument();
  });

  it("ofrece recuperación cuando el catálogo no se puede cargar", async () => {
    let attempt = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        attempt += 1;
        if (attempt === 1) {
          return Response.json({ detail: "sin conexión" }, { status: 503 });
        }
        return Response.json({
          skills: [],
          summary: { active: 0, drafts: 0 },
          available_tools: [tool],
        });
      }),
    );
    renderPage();

    expect(
      await screen.findByText("No se pudo abrir Skill Studio. Vuelve a intentarlo."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));

    await waitFor(() =>
      expect(screen.getByText("Aún no has creado ninguna skill.")).toBeInTheDocument(),
    );
  });
});
