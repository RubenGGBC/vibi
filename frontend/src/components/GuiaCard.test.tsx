import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GuiaCard } from "./GuiaCard";
import type { Guia } from "../types";

// La imagen se pide con el token, como los archivos. Aquí se sustituye por un
// blob de mentira: lo que se prueba es dónde caen las marcas y qué se lee en la
// leyenda, no que `fetch` sepa traer un JPEG.
const pedidas: string[] = [];
vi.mock("../lib/api", () => ({
  apiBlob: async (url: string) => {
    pedidas.push(url);
    if (url.includes("caducada")) throw new Error("404");
    return new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" });
  },
}));

const guia = (extra: Partial<Guia> = {}): Guia => ({
  id: "g1",
  imagen_url: "/api/guias/g1/imagen",
  caduca_en: Date.now() / 1000 + 600,
  ventana: "Ajustes",
  pantalla: "pantalla 1 (principal)",
  ancho: 1568,
  alto: 882,
  marcas: [
    {
      numero: 1,
      ref: "e12",
      rol: "boton",
      nombre: "Idioma",
      texto: "aquí se cambia",
      x: 100,
      y: 200,
      ancho: 120,
      alto: 40,
      recortada: false,
    },
  ],
  fuera: [],
  ...extra,
});

describe("GuiaCard", () => {
  it("dibuja la marca donde dice el árbol, en coordenadas de la foto", async () => {
    const { container } = render(<GuiaCard guia={guia()} />);

    const svg = container.querySelector("svg.guia-marcas");
    expect(svg?.getAttribute("viewBox")).toBe("0 0 1568 882");
    const rect = container.querySelector("svg.guia-marcas rect");
    expect(rect?.getAttribute("x")).toBe("100");
    expect(rect?.getAttribute("y")).toBe("200");
    expect(rect?.getAttribute("width")).toBe("120");
    expect(rect?.getAttribute("height")).toBe("40");
  });

  it("la leyenda dice qué es cada número", async () => {
    render(<GuiaCard guia={guia()} />);

    // El número sale dos veces —sobre la foto y en la leyenda— y es a
    // propósito: la marca sin leyenda no dice qué es, y la leyenda sin marca no
    // dice dónde.
    expect(screen.getByText("1", { selector: ".guia-numero" })).toBeInTheDocument();
    expect(screen.getByText("1", { selector: "text" })).toBeInTheDocument();
    expect(screen.getByText("aquí se cambia")).toBeInTheDocument();
  });

  it("sin etiqueta propia, la leyenda usa el nombre del elemento", () => {
    render(<GuiaCard guia={guia({
      marcas: [{ ...guia().marcas[0], texto: "" }],
    })} />);

    expect(screen.getByText("Idioma")).toBeInTheDocument();
  });

  it("pide la imagen a la URL autenticada de esa guía", async () => {
    render(<GuiaCard guia={guia()} />);

    await waitFor(() =>
      expect(pedidas).toContain("/api/guias/g1/imagen"),
    );
  });

  it("lo que no se pudo señalar se dice, no se calla", () => {
    render(<GuiaCard guia={guia({ fuera: ["e13"] })} />);

    expect(screen.getByText(/No se veía en esa pantalla/)).toBeInTheDocument();
  });

  it("una guía caducada lo explica en vez de dar error", async () => {
    render(<GuiaCard guia={guia({ imagen_url: "/api/guias/caducada/imagen" })} />);

    expect(
      await screen.findByText(/no se guardan/),
    ).toBeInTheDocument();
  });
});
