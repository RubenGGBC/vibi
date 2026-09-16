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
    const silhouette = rig.svg.querySelector(".companion-vibi-white-silhouette");
    expect(silhouette).not.toBeNull();
    expect(silhouette?.getAttribute("fill-rule")).toBe("evenodd");
    expect(rig.svg.querySelector(".companion-vibi-flame-outline")).toBeNull();
    expect(
      rig.flameTongues.every(
        (tongue) =>
          tongue.querySelector(".companion-vibi-flame-outer")?.getAttribute("stroke") === null,
      ),
    ).toBe(true);
  });

  it("protege la diagonal, la copa dominante y la asimetría de la referencia", () => {
    const { hatTop, brimLeft, brimRight, jawTip, flameTip } = REFERENCE_LANDMARKS;
    const rig = createCompanionRig("landmarks");

    expect(REFERENCE_LANDMARKS).toEqual({
      hatTop: { x: 257, y: 35 },
      brimLeft: { x: 52, y: 262 },
      brimRight: { x: 337, y: 165 },
      jawTip: { x: 223, y: 348 },
      flameTip: { x: 355, y: 158 },
    });
    expect(brimRight.x - brimLeft.x).toBeGreaterThan(280);
    expect(brimRight.y - brimLeft.y).toBeLessThan(-80);
    expect(brimLeft.y - hatTop.y).toBeGreaterThan(200);
    expect(jawTip.x).toBeLessThan(flameTip.x);
    expect(flameTip.x).toBeGreaterThan(brimRight.x);
    expect(flameTip.y).toBeLessThan(jawTip.y);
    expect(rig.svg.querySelector(".companion-vibi-crown-traced")).not.toBeNull();
    expect(rig.svg.querySelector(".companion-vibi-brim-traced")).not.toBeNull();
    expect(rig.svg.querySelectorAll(".companion-vibi-fold")).toHaveLength(1);
  });

  it("aísla gradientes y recortes entre escenas", () => {
    const a = createCompanionRig("a");
    const b = createCompanionRig("b");

    expect(a.svg.innerHTML).toContain("url(#a-hat-gradient)");
    expect(b.svg.innerHTML).toContain("url(#b-hat-gradient)");
    expect(a.svg.innerHTML).not.toContain("url(#b-");
  });
});
