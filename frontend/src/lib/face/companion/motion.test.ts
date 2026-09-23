import { describe, expect, it } from "vitest";

import { SENALES_QUIETAS } from "../modificadores";
import { createCompanionMotion } from "./motion";

describe("movimiento del companion", () => {
  it("mantiene viva la llama y retrasa la chistera", () => {
    const motion = createCompanionMotion("reposo");
    const first = motion.advance(1 / 60, 1_000, 0, SENALES_QUIETAS, false);
    const later = motion.advance(1 / 60, 1_200, 0, SENALES_QUIETAS, false);

    expect(later.flameScale).not.toEqual(first.flameScale);
    expect(later.hat.rotation).not.toBe(later.body.rotation);
  });

  it("hace anticipación y salto al entrar en contenta", () => {
    const motion = createCompanionMotion("reposo");
    motion.setFamily("contenta");
    const first = motion.advance(1 / 60, 1_000, 0, SENALES_QUIETAS, false);
    let highest = first.body.y;

    for (let i = 1; i < 45; i += 1) {
      const frame = motion.advance(1 / 60, 1_000 + i * 16.67, 0, SENALES_QUIETAS, false);
      highest = Math.min(highest, frame.body.y);
    }

    expect(first.body.scaleY).not.toBeCloseTo(1, 3);
    expect(highest).toBeLessThan(-8);
  });

  it("lleva la mirada al puntero y después la suelta", () => {
    const motion = createCompanionMotion("reposo");
    motion.setPointer(1, -1);
    const pointed = motion.advance(0.1, 1_000, 0, SENALES_QUIETAS, false);

    expect(pointed.look.x).toBeGreaterThan(0);
    expect(pointed.look.y).toBeLessThan(0);

    motion.clearPointer();
    const released = motion.advance(0.5, 1_500, 0, SENALES_QUIETAS, false);
    expect(Math.abs(released.look.x)).toBeLessThan(Math.abs(pointed.look.x));
  });

  it("con movimiento reducido devuelve una pose estable", () => {
    const motion = createCompanionMotion("contenta");
    const first = motion.advance(1 / 60, 1_000, 1, SENALES_QUIETAS, true);
    const later = motion.advance(1 / 60, 5_000, 0, SENALES_QUIETAS, true);

    expect(later).toEqual(first);
  });
});
