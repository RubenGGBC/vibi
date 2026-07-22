import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearToken, getToken } from "../lib/auth";
import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  afterEach(() => {
    clearToken();
    vi.unstubAllGlobals();
  });

  it("guarda el token y vuelve al destino solicitado", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ token: "jwt-nuevo" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter
          initialEntries={[{ pathname: "/login", state: { from: "/chat" } }]}
        >
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/chat" element={<p>Destino chat</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.type(screen.getByLabelText("Nombre"), "ruben");
    await userEvent.type(screen.getByLabelText("Contraseña"), "correcta");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByText("Destino chat")).toBeInTheDocument();
    expect(getToken()).toBe("jwt-nuevo");
  });
});
