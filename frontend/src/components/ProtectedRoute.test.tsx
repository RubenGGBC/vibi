import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { clearToken, setToken } from "../lib/auth";
import { ProtectedRoute } from "./ProtectedRoute";

describe("ProtectedRoute", () => {
  afterEach(clearToken);

  it("redirige al login conservando el destino", () => {
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/login" element={<p>Acceso</p>} />
          <Route element={<ProtectedRoute />}>
            <Route path="/chat" element={<p>Chat privado</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("Acceso")).toBeInTheDocument();
    expect(screen.queryByText("Chat privado")).not.toBeInTheDocument();
  });

  it("muestra la ruta si hay token", () => {
    setToken("jwt");
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route element={<ProtectedRoute />}>
            <Route path="/chat" element={<p>Chat privado</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("Chat privado")).toBeInTheDocument();
  });
});
