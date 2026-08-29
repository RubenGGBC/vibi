import { afterEach, describe, expect, it, vi } from "vitest";

import { SENALES_QUIETAS } from "../modificadores";
import { callarOido, publicarNivelDeVoz } from "../oido";
import { createCompanionScene } from "./scene";

afterEach(() => {
  callarOido();
  vi.restoreAllMocks();
});

describe("escena SVG del companion", () => {
  it("monta reposo en el primer fotograma y se retira al disponer", () => {
    const container = document.createElement("div");
    const scene = createCompanionScene(container);
    const svg = container.querySelector(".companion-vibi-svg");

    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("data-family")).toBe("reposo");
    expect(svg?.innerHTML).not.toContain("NaN");

    scene.dispose();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("mueve cuerpo y sombrero sin sustituir la figura maestra", () => {
    const container = document.createElement("div");
    const scene = createCompanionScene(container);
    const face = container.querySelector("[data-vibi-part='face']");

    scene.setState("pleased");
    scene.dibujar(1 / 60);

    expect(container.querySelector("[data-vibi-part='face']")).toBe(face);
    expect(container.querySelector(".companion-vibi-body")?.getAttribute("transform")).toMatch(/rotate/);
    expect(container.querySelector(".companion-vibi-hat")?.getAttribute("transform")).toMatch(/rotate/);
    scene.dispose();
  });

  it.each([
    ["thinking", "duda", ".companion-vibi-question"],
    ["speaking", "hablando", ".companion-vibi-wave"],
    ["hacking", "ejecutando", ".companion-vibi-terminal"],
    ["searching", "buscando", ".companion-vibi-magnifier"],
  ] as const)("anima el complemento de %s", (state, family, selector) => {
    const container = document.createElement("div");
    const scene = createCompanionScene(container);

    scene.setState(state);
    scene.dibujar(1 / 60);

    const svg = container.querySelector(".companion-vibi-svg");
    const accessory = container.querySelector(selector);
    expect(svg?.getAttribute("data-family")).toBe(family);
    expect(accessory?.getAttribute("opacity")).toBe("1");
    expect(accessory?.getAttribute("transform") ?? accessory?.getAttribute("data-level")).toBeTruthy();
    scene.dispose();
  });

  it("dibuja de inmediato y limita deltas grandes", () => {
    const container = document.createElement("div");
    const scene = createCompanionScene(container);
    const svg = container.querySelector(".companion-vibi-svg");

    expect(svg?.getAttribute("data-frame")).toBe("1");
    scene.dibujar(9);
    expect(svg?.innerHTML).not.toContain("NaN");
    scene.dispose();
  });

  it("reacciona a voz, puntero y señales", () => {
    const container = document.createElement("div");
    const scene = createCompanionScene(container);

    scene.setState("speaking");
    publicarNivelDeVoz(0.18);
    scene.setPointer(1, -1);
    scene.setSenales({ ...SENALES_QUIETAS, cadencia: 30, pasos: 8 });
    scene.dibujar(0.1);

    expect(Number(container.querySelector(".companion-vibi-wave")?.getAttribute("data-level"))).toBeGreaterThan(0.5);
    expect(container.querySelector(".companion-vibi-eyes")?.innerHTML).toMatch(/translate\([^0]/);
    scene.dispose();
  });

  it("cancela el bucle y deja de escribir tras dispose", () => {
    const cancel = vi.spyOn(window, "cancelAnimationFrame");
    const container = document.createElement("div");
    const scene = createCompanionScene(container);

    scene.dispose();
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(container.querySelector("svg")).toBeNull();

    scene.setState("recelo");
    scene.dibujar(1 / 60);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("permite congelar las ocho familias para revisión", () => {
    const requestFrame = vi.spyOn(window, "requestAnimationFrame");
    const representatives = [
      "idle",
      "recelo",
      "pleased",
      "working",
      "thinking",
      "speaking",
      "hacking",
      "searching",
    ] as const;
    const families = representatives.map((state) => {
      const container = document.createElement("div");
      const scene = createCompanionScene(container, { frozen: true });
      scene.setState(state);
      scene.dibujar(1 / 60);
      const family = container.querySelector("svg")?.getAttribute("data-family");
      scene.dispose();
      return family;
    });

    expect(families).toEqual([
      "reposo",
      "recelo",
      "contenta",
      "trabajando",
      "duda",
      "hablando",
      "ejecutando",
      "buscando",
    ]);
    expect(requestFrame).not.toHaveBeenCalled();
  });
});
