import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Tool } from "../types";
import { ToolsPage } from "./ToolsPage";

const usage = {
  total: 0,
  succeeded: 0,
  failed: 0,
  denied: 0,
  success_rate: null,
  last_used_at: null,
  average_duration_ms: null,
};

const health: Tool = {
  id: "system.health",
  name: "Estado de Morgana",
  description: "Comprueba que Morgana responde.",
  scope: "system",
  primitive_id: "system.health",
  permissions: [],
  effects: [],
  input_schema: { type: "object", properties: {} },
  enabled: true,
  source: "builtin",
  created_at: null,
  updated_at: null,
  editable: false,
  duplicable: true,
  usage,
};

const createNote: Tool = {
  id: "files.create_note",
  name: "Crear una nota",
  description: "Guarda una nota de texto como archivo gestionado.",
  scope: "system",
  primitive_id: "files.create_note",
  permissions: ["files:write:self"],
  effects: ["filesystem:write"],
  input_schema: {
    type: "object",
    required: ["name", "content"],
    properties: {
      name: { title: "Name", type: "string", minLength: 1, maxLength: 255 },
      content: {
        title: "Content",
        type: "string",
        minLength: 1,
        maxLength: 100000,
      },
    },
  },
  enabled: true,
  source: "builtin",
  created_at: null,
  updated_at: null,
  editable: false,
  duplicable: true,
  usage,
};

const advancedTool: Tool = {
  ...health,
  id: "system.advanced",
  primitive_id: "system.advanced",
  name: "Configuración avanzada",
  input_schema: {
    type: "object",
    required: ["options"],
    properties: {
      options: { title: "Opciones JSON", type: "object" },
    },
  },
};

const typedFormTool: Tool = {
  ...health,
  id: "system.typed_form",
  primitive_id: "system.typed_form",
  name: "Formulario tipado",
  input_schema: {
    type: "object",
    required: ["enabled"],
    properties: {
      enabled: { title: "Activada", type: "boolean" },
      mode: { title: "Modo", enum: ["safe", "fast"] },
      nullable_flag: {
        title: "Indicador opcional",
        type: ["boolean", "null"],
        default: null,
      },
    },
  },
};

const removedPrimitiveTool: Tool = {
  ...health,
  id: "custom-removed",
  name: "Tool obsoleta",
  description: "Conserva una referencia histórica.",
  scope: "personal",
  primitive_id: "legacy.removed",
  input_schema: {},
  bound_arguments: { legacy: true },
  enabled: false,
  source: "human",
  created_at: 1_700_000_000,
  editable: true,
  duplicable: false,
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ToolsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ToolsPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("genera presets desde el esquema y solo guarda los campos elegidos", async () => {
    const request = { body: null as Record<string, unknown> | null };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") {
          request.body = JSON.parse(String(init.body)) as Record<string, unknown>;
          return Response.json({ ...createNote, id: "custom-1", scope: "personal" }, { status: 201 });
        }
        return Response.json({ herramientas: [health, createNote] });
      }),
    );
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Estado de Morgana" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Crear una nota" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Crear tool" }));
    await userEvent.type(screen.getByLabelText("Nombre"), "Bitácora diaria");
    await userEvent.type(
      screen.getByLabelText("Descripción"),
      "Guarda una entrada con nombre estable",
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Capacidad base"),
      "files.create_note",
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Preconfigurar Nombre del archivo" }),
    );
    await userEvent.type(
      screen.getByLabelText("Nombre del archivo preconfigurado"),
      "diario.md",
    );
    await userEvent.click(screen.getByRole("button", { name: "Crear herramienta" }));

    await waitFor(() => expect(request.body).not.toBeNull());
    expect(request.body).toMatchObject({
      name: "Bitácora diaria",
      primitive_id: "files.create_note",
      bound_arguments: { name: "diario.md" },
    });
    expect(
      (request.body?.bound_arguments as Record<string, unknown>).content,
    ).toBeUndefined();
  });

  it("ejecuta una primitiva con argumentos generados por el esquema", async () => {
    let executionBody: Record<string, unknown> | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/files.create_note/ejecutar")) {
          executionBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
          return Response.json({
            invocation_id: "inv-1",
            status: "succeeded",
            result: { file: { name: "ideas.md", size_bytes: 14 } },
          });
        }
        return Response.json({ herramientas: [health, createNote] });
      }),
    );
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Probar Crear una nota" }),
    );
    await userEvent.type(screen.getByLabelText("Nombre del archivo"), "ideas.md");
    await userEvent.type(screen.getByLabelText("Contenido"), "Primera idea");
    await userEvent.click(screen.getByRole("button", { name: "Ejecutar ahora" }));

    expect(await screen.findByText(/ideas\.md/)).toBeInTheDocument();
    expect(executionBody).toEqual({
      arguments: { name: "ideas.md", content: "Primera idea" },
    });
  });

  it("muestra el historial personal de una herramienta", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/system.health/invocaciones")) {
          return Response.json({
            invocations: [
              {
                id: "inv-2",
                tool_id: "system.health",
                status: "denied",
                error_code: "invalid_arguments",
                requested_at: 1_700_000_001,
                completed_at: 1_700_000_001.01,
                duration_ms: 10,
              },
              {
                id: "inv-1",
                tool_id: "system.health",
                status: "succeeded",
                error_code: null,
                requested_at: 1_700_000_000,
                completed_at: 1_700_000_000.1,
                duration_ms: 100,
              },
            ],
          });
        }
        return Response.json({ herramientas: [health, createNote] });
      }),
    );
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Historial Estado de Morgana" }),
    );

    expect(await screen.findByText("Correcta")).toBeInTheDocument();
    expect(screen.getByText("Argumentos inválidos")).toBeInTheDocument();
    expect(screen.getByText("100 ms")).toBeInTheDocument();
  });

  it("convierte el fallback JSON para esquemas futuros", async () => {
    const request = { body: null as Record<string, unknown> | null };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/system.advanced/ejecutar")) {
          request.body = JSON.parse(String(init?.body)) as Record<string, unknown>;
          return Response.json({
            invocation_id: "inv-json",
            status: "succeeded",
            result: { accepted: true },
          });
        }
        return Response.json({ herramientas: [advancedTool] });
      }),
    );
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Probar Configuración avanzada" }),
    );
    fireEvent.change(screen.getByLabelText("Opciones JSON"), {
      target: { value: '{"mode":"safe"}' },
    });
    await userEvent.click(screen.getByRole("button", { name: "Ejecutar ahora" }));

    expect(request.body).toEqual({ arguments: { options: { mode: "safe" } } });
  });

  it("distingue false de unset y omite un enum opcional limpio", async () => {
    const request = { body: null as Record<string, unknown> | null };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/system.typed_form/ejecutar")) {
          request.body = JSON.parse(String(init?.body)) as Record<string, unknown>;
          return Response.json({
            invocation_id: "inv-typed",
            status: "succeeded",
            result: { accepted: true },
          });
        }
        return Response.json({ herramientas: [typedFormTool] });
      }),
    );
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Probar Formulario tipado" }),
    );
    expect(
      screen.getByRole("combobox", { name: "Activada" }),
    ).toHaveValue("false");
    expect(
      screen.getByRole("combobox", { name: "Indicador opcional" }),
    ).toHaveValue("");
    await userEvent.selectOptions(screen.getByLabelText("Modo"), "safe");
    await userEvent.selectOptions(screen.getByLabelText("Modo"), "");
    await userEvent.click(screen.getByRole("button", { name: "Ejecutar ahora" }));

    expect(request.body).toEqual({ arguments: { enabled: false } });
  });

  it("conserva false al preconfigurar un booleano", async () => {
    const request = { body: null as Record<string, unknown> | null };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") {
          request.body = JSON.parse(String(init.body)) as Record<string, unknown>;
          return Response.json({ ...typedFormTool, id: "custom-typed", scope: "personal" }, { status: 201 });
        }
        return Response.json({ herramientas: [health, typedFormTool] });
      }),
    );
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Crear tool" }));
    await userEvent.type(screen.getByLabelText("Nombre"), "Formulario fijo");
    await userEvent.type(screen.getByLabelText("Descripción"), "Mantiene un booleano falso");
    await userEvent.selectOptions(screen.getByLabelText("Capacidad base"), "system.typed_form");
    await userEvent.click(
      screen.getByRole("checkbox", {
        name: "Preconfigurar Indicador opcional",
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Crear herramienta" }));

    expect(request.body).toMatchObject({
      bound_arguments: { nullable_flag: false },
    });
  });

  it("no revincula silenciosamente una primitiva retirada", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ herramientas: [health, removedPrimitiveTool] }),
      ),
    );
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Editar Tool obsoleta" }),
    );
    const capability = screen.getByLabelText("Capacidad base");

    expect(capability).toHaveValue("legacy.removed");
    expect(
      screen.getByRole("option", { name: "legacy.removed · retirada" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Guardar cambios" })).toBeDisabled();

    await userEvent.selectOptions(capability, "system.health");
    expect(screen.getByRole("button", { name: "Guardar cambios" })).toBeEnabled();
  });
});
