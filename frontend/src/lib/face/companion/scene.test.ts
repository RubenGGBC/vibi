import { describe, expect, it } from "vitest";

import { createCompanionScene } from "./scene";

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
});
