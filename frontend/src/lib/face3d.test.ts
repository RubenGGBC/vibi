import { describe, expect, it } from "vitest";

import { createFaceScene, supportsWebGL } from "./face3d";

describe("face3d", () => {
  it("detecta que jsdom no ofrece WebGL", () => {
    expect(supportsWebGL()).toBe(false);
  });

  it("devuelve null en vez de lanzar cuando no se puede crear el contexto", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);

    expect(createFaceScene(host)).toBeNull();
    // sin escena no debe quedar ningún lienzo colgado en el contenedor
    expect(host.querySelector("canvas")).toBeNull();

    host.remove();
  });
});
