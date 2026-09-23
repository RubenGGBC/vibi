import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MessageComposer } from "./MessageComposer";
import type { UserFile } from "../types";

const archivo: UserFile = {
  id: "f1",
  name: "receta.txt",
  source: "managed",
  project_id: null,
  relative_path: null,
  media_type: "text/plain",
  size_bytes: 12,
  modified_at: 1,
  created_at: 1,
  download_url: "/api/archivos/f1/contenido",
};

const propiedades = {
  label: "Mensaje",
  placeholder: "Escribe un mensaje…",
  submitLabel: "Enviar mensaje",
};

describe("MessageComposer", () => {
  it("sin onAdjuntar no enseña el clip", () => {
    render(<MessageComposer {...propiedades} onSubmit={vi.fn()} />);
    expect(
      screen.queryByRole("button", { name: "Adjuntar archivo" }),
    ).not.toBeInTheDocument();
  });

  it("deja enviar un mensaje que solo lleva archivos", async () => {
    const onSubmit = vi.fn();
    render(
      <MessageComposer
        {...propiedades}
        onSubmit={onSubmit}
        adjuntos={[archivo]}
        onAdjuntar={vi.fn()}
      />,
    );

    // «Mira esto» está en el archivo, no en el texto: el botón no puede estar
    // apagado solo porque el textarea siga vacío.
    await userEvent.click(screen.getByRole("button", { name: "Enviar mensaje" }));
    expect(onSubmit).toHaveBeenCalledWith("Te adjunto un archivo.");
  });

  it("sin texto ni archivos no se puede enviar", () => {
    render(
      <MessageComposer {...propiedades} onSubmit={vi.fn()} onAdjuntar={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Enviar mensaje" })).toBeDisabled();
  });

  it("quita un adjunto desde su ficha", async () => {
    const onQuitar = vi.fn();
    render(
      <MessageComposer
        {...propiedades}
        onSubmit={vi.fn()}
        adjuntos={[archivo]}
        onAdjuntar={vi.fn()}
        onQuitarAdjunto={onQuitar}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Quitar receta.txt" }));
    expect(onQuitar).toHaveBeenCalledWith("f1");
  });
});
