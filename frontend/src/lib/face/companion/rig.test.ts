import { describe, expect, it } from "vitest";

import { REFERENCE_LANDMARKS } from "./geometry";
import { createCompanionRig } from "./rig";

describe("rig vectorial del companion", () => {
  it("monta la silueta maestra en seis grupos reutilizables", () => {
    const rig = createCompanionRig("test");

    expect(rig.svg.getAttribute("viewBox")).toBe("0 0 420 360");
    for (const name of ["hat", "face", "jaw", "eyes", "flame", "accessories"]) {
      expect(rig.svg.querySelector(`[data-vibi-part='${name}']`)).not.toBeNull();
    }
    expect(rig.flameTongues).toHaveLength(3);
  });

  it("protege la diagonal, la copa dominante y la asimetría de la referencia", () => {
    const { hatTop, brimLeft, brimRight, jawTip, flameTip } = REFERENCE_LANDMARKS;

    expect(brimRight.x - brimLeft.x).toBeGreaterThan(280);
    expect(brimRight.y - brimLeft.y).toBeLessThan(-40);
    expect(brimLeft.y - hatTop.y).toBeGreaterThan(130);
    expect(jawTip.x).toBeLessThan(210);
    expect(flameTip.x).toBeGreaterThan(brimRight.x);
    expect(flameTip.y).toBeLessThan(jawTip.y);
  });

  it("aísla gradientes y recortes entre escenas", () => {
    const a = createCompanionRig("a");
    const b = createCompanionRig("b");

    expect(a.svg.innerHTML).toContain("url(#a-hat-gradient)");
    expect(b.svg.innerHTML).toContain("url(#b-hat-gradient)");
    expect(a.svg.innerHTML).not.toContain("url(#b-");
  });
});
