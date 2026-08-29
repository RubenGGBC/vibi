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
});
