import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UserFile } from "../types";
import { FilesPage } from "./FilesPage";

const file = (name: string, path: string): UserFile => ({
  id: path,
  name,
  source: "workspace",
  relative_path: path,
  media_type: "text/plain",
  size_bytes: 4,
  modified_at: 1,
  created_at: 1,
  download_url: `/api/archivos/${path}/contenido`,
});

describe("FilesPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("abre carpetas y permite volver al nivel anterior", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("ruta=documentos")) {
        return Response.json({
          ruta: "documentos",
          carpetas: [],
          archivos: [file("matricula.pdf", "documentos/matricula.pdf")],
        });
      }
      return Response.json({
        ruta: "",
        carpetas: [{ name: "documentos", path: "documentos" }],
        archivos: [file("portada.txt", "portada.txt")],
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <FilesPage />
      </QueryClientProvider>,
    );

    await userEvent.click(
      await screen.findByRole("button", { name: /documentos/i }),
    );
    expect(await screen.findByText("matricula.pdf")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "documentos" }),
    ).toHaveAttribute("aria-current", "page");

    await userEvent.click(
      screen.getByRole("button", { name: "Volver a la carpeta anterior" }),
    );
    expect(await screen.findByText("portada.txt")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/archivos?ruta=documentos&limite=100",
      expect.any(Object),
    );
  });
});
