import { describe, expect, it } from "vitest";

import { ESTADOS } from "../estados";
import { FAMILY_BY_STATE, POSES, familyOf } from "./states";

describe("familias del companion", () => {
  it("cubre una vez todos los estados actuales", () => {
    expect(Object.keys(FAMILY_BY_STATE).sort()).toEqual([...ESTADOS].sort());
  });

  it("conserva las ocho familias aprobadas", () => {
    expect(new Set(Object.values(FAMILY_BY_STATE))).toEqual(
      new Set([
        "reposo",
        "recelo",
        "contenta",
        "trabajando",
        "duda",
        "hablando",
        "ejecutando",
        "buscando",
      ]),
    );
    expect(Object.keys(POSES).sort()).toEqual([
      "buscando",
      "contenta",
      "duda",
      "ejecutando",
      "hablando",
      "recelo",
      "reposo",
      "trabajando",
    ]);
  });

  it("mapea los estados representativos y protege valores desconocidos", () => {
    expect(familyOf("idle")).toBe("reposo");
    expect(familyOf("recelo")).toBe("recelo");
    expect(familyOf("pleased")).toBe("contenta");
    expect(familyOf("working")).toBe("trabajando");
    expect(familyOf("thinking")).toBe("duda");
    expect(familyOf("speaking")).toBe("hablando");
    expect(familyOf("hacking")).toBe("ejecutando");
    expect(familyOf("searching")).toBe("buscando");
    expect(familyOf("estado-futuro")).toBe("reposo");
  });
});
