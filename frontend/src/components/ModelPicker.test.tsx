import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ModelPicker } from "./ModelPicker";
import type { AgyModelo } from "./ModelPicker";

const conEffort: AgyModelo = {
  id: "gemini-3.8-flash-high",
  etiqueta: "Gemini 3.8 Flash (High)",
  effort_en_el_nombre: true,
};

const sinEffort: AgyModelo = {
  id: "claude-sonnet-4-6",
  etiqueta: "Claude Sonnet 4.6 (Thinking)",
  effort_en_el_nombre: false,
};

describe("ModelPicker", () => {
  it("empieza cerrado: no se ve ningún modelo hasta pulsar el botón", () => {
    render(
      <ModelPicker modelos={[conEffort]} cargando={false} error={null} onElegir={vi.fn()} />,
    );

    expect(screen.queryByText(conEffort.etiqueta)).not.toBeInTheDocument();
  });

  it("al abrirlo se ven los modelos recibidos", async () => {
    render(
      <ModelPicker modelos={[conEffort]} cargando={false} error={null} onElegir={vi.fn()} />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));

    expect(screen.getByText(conEffort.etiqueta)).toBeInTheDocument();
  });

  it("un modelo que ya lleva el effort en el nombre se elige de un solo clic", async () => {
    const onElegir = vi.fn();
    render(
      <ModelPicker modelos={[conEffort]} cargando={false} error={null} onElegir={onElegir} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));

    await userEvent.click(screen.getByText(conEffort.etiqueta));

    expect(onElegir).toHaveBeenCalledWith("/model gemini-3.8-flash-high");
  });

  it("un modelo sin effort en el nombre pide elegirlo antes de mandar el comando", async () => {
    const onElegir = vi.fn();
    render(
      <ModelPicker modelos={[sinEffort]} cargando={false} error={null} onElegir={onElegir} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));
    await userEvent.click(screen.getByText(sinEffort.etiqueta));

    expect(onElegir).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "high" })).toBeInTheDocument();
  });

  it("elegir el effort completa el comando con los dos datos", async () => {
    const onElegir = vi.fn();
    render(
      <ModelPicker modelos={[sinEffort]} cargando={false} error={null} onElegir={onElegir} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));
    await userEvent.click(screen.getByText(sinEffort.etiqueta));

    await userEvent.click(screen.getByRole("button", { name: "high" }));

    expect(onElegir).toHaveBeenCalledWith("/model claude-sonnet-4-6 high");
  });

  it("avisa al abrirse, para que quien lo usa pida la lista solo entonces", async () => {
    const onAbrir = vi.fn();
    render(
      <ModelPicker
        modelos={[]}
        cargando={false}
        error={null}
        onElegir={vi.fn()}
        onAbrir={onAbrir}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));

    expect(onAbrir).toHaveBeenCalledOnce();
  });

  it("no vuelve a avisar al cerrarlo", async () => {
    const onAbrir = vi.fn();
    render(
      <ModelPicker
        modelos={[]}
        cargando={false}
        error={null}
        onElegir={vi.fn()}
        onAbrir={onAbrir}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));
    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));

    expect(onAbrir).toHaveBeenCalledOnce();
  });

  it("«Por defecto» manda /model default", async () => {
    const onElegir = vi.fn();
    render(<ModelPicker modelos={[]} cargando={false} error={null} onElegir={onElegir} />);
    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));

    await userEvent.click(screen.getByText("Por defecto"));

    expect(onElegir).toHaveBeenCalledWith("/model default");
  });

  it("mientras carga lo dice en vez de enseñar una lista vacía", async () => {
    render(<ModelPicker modelos={[]} cargando error={null} onElegir={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));

    expect(screen.getByText(/Preguntando a agy/)).toBeInTheDocument();
  });

  it("un error de agy se enseña en vez de callarse", async () => {
    render(
      <ModelPicker
        modelos={[]}
        cargando={false}
        error="agy no contesta"
        onElegir={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Modelo/ }));

    expect(screen.getByText("agy no contesta")).toBeInTheDocument();
  });
});
