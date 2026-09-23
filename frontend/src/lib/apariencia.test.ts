import { beforeEach, describe, expect, it } from "vitest";

import { APARIENCIA_ORIGINAL, aplicarApariencia } from "./apariencia";
import type { AparienciaVibi } from "../types";

const variable = (nombre: string) =>
  document.documentElement.style.getPropertyValue(nombre);

describe("aplicar la identidad a la ventana", () => {
  beforeEach(() => {
    document.documentElement.style.cssText = "";
  });

  it("pinta los tres colores y los derivados del sombrero", () => {
    aplicarApariencia({
      color_cara: "#FFFFFF",
      color_antifaz: "#0C0714",
      color_sombrero: "#F4121B",
      actualizada_en: 0,
    });
    expect(variable("--vibi-identidad-cara")).toBe("#FFFFFF");
    expect(variable("--vibi-identidad-antifaz")).toBe("#0C0714");
    expect(variable("--vibi-identidad-sombrero")).toBe("#F4121B");
    expect(variable("--vibi-identidad-sombrero-sombra")).toBe("#a60c12");
    expect(variable("--vibi-identidad-resplandor")).toBe("244 18 27");
  });

  // El servidor puede devolver un cuerpo incompleto —una migración a medias,
  // un 200 con menos campos de los que dice el tipo—, y esto corre dentro de
  // un `useEffect` sin error boundary encima: un `undefined.slice` aquí no
  // desluce el color, tumba la ventana entera. Lo que falte se rellena con la
  // identidad original en vez de reventar.
  it("no revienta si el servidor manda la apariencia a medias", () => {
    expect(() =>
      aplicarApariencia({ color_cara: "#123456" } as AparienciaVibi),
    ).not.toThrow();
    expect(variable("--vibi-identidad-cara")).toBe("#123456");
    expect(variable("--vibi-identidad-sombrero")).toBe(
      APARIENCIA_ORIGINAL.color_sombrero,
    );
    expect(variable("--vibi-identidad-sombrero-sombra")).toBe("#a60c12");
  });

  it("no revienta si el cuerpo viene vacío del todo", () => {
    expect(() => aplicarApariencia({} as AparienciaVibi)).not.toThrow();
    expect(variable("--vibi-identidad-cara")).toBe(
      APARIENCIA_ORIGINAL.color_cara,
    );
    expect(variable("--vibi-identidad-antifaz")).toBe(
      APARIENCIA_ORIGINAL.color_antifaz,
    );
  });
});

describe("colores que llegan rotos", () => {
  beforeEach(() => {
    document.documentElement.style.cssText = "";
  });

  // JSON distingue "no viene el campo" de "viene a null", y el segundo se
  // colaba igual de roto por un spread.
  it("trata un color a null como si no hubiera venido", () => {
    expect(() =>
      aplicarApariencia({
        color_cara: "#123456",
        color_antifaz: null,
        color_sombrero: null,
        actualizada_en: 0,
      } as unknown as AparienciaVibi),
    ).not.toThrow();
    expect(variable("--vibi-identidad-antifaz")).toBe(
      APARIENCIA_ORIGINAL.color_antifaz,
    );
    expect(variable("--vibi-identidad-sombrero")).toBe(
      APARIENCIA_ORIGINAL.color_sombrero,
    );
  });
});
