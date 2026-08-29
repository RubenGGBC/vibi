import {
  acotar,
  avanzarMuelle,
  crearMuelle,
  crearSeguimientoPuntero,
  fijarMuelle,
  pulso,
} from "../../faceMotion";
import { ajustesDe, type Senales } from "../modificadores";
import { POSES, type CompanionFamily } from "./states";

export interface CompanionTransform {
  x: number;
  y: number;
  rotation: number;
  scaleX: number;
  scaleY: number;
}

export interface CompanionFrame {
  body: CompanionTransform;
  /** Transformación relativa al cuerpo: el sombrero ya está dentro de él. */
  hat: CompanionTransform;
  look: { x: number; y: number };
  /** 1 abierto; 0 cerrado. */
  blink: number;
  flameScale: readonly [number, number, number];
  accessoryOpacity: number;
  accessoryProgress: number;
  voice: number;
}

export interface CompanionMotion {
  setFamily(family: CompanionFamily): void;
  setPointer(x: number, y: number): void;
  clearPointer(): void;
  advance(
    delta: number,
    now: number,
    voice: number,
    signals: Senales,
    reduced: boolean,
  ): CompanionFrame;
}

const ease = (current: number, target: number, delta: number, tau: number): number =>
  current + (target - current) * (1 - Math.exp(-delta / tau));

const transform = (
  y = 0,
  rotation = 0,
  scaleX = 1,
  scaleY = 1,
): CompanionTransform => ({ x: 0, y, rotation, scaleX, scaleY });

/** Parpadeo determinista: irregular sin introducir azar en escenas ni pruebas. */
const blinkAt = (elapsed: number): number => {
  const waits = [2.8, 4.1, 3.3];
  const duration = 0.13;
  const cycle = waits.reduce((sum, wait) => sum + wait + duration, 0);
  let cursor = elapsed % cycle;
  for (const wait of waits) {
    if (cursor < wait) return 1;
    cursor -= wait;
    if (cursor <= duration) return Math.abs(Math.cos((cursor / duration) * Math.PI));
    cursor -= duration;
  }
  return 1;
};

const staticFrame = (family: CompanionFamily): CompanionFrame => ({
  body: transform(0, POSES[family].baseTilt),
  hat: transform(),
  look: { x: 0, y: 0 },
  blink: 1,
  flameScale: [1, 1, 1],
  accessoryOpacity: 1,
  accessoryProgress: 0.5,
  voice: 0,
});

export function createCompanionMotion(
  initial: CompanionFamily = "reposo",
): CompanionMotion {
  let family = initial;
  let elapsed = 0;
  let transitionAge = Number.POSITIVE_INFINITY;
  let lookX = 0;
  let lookY = 0;

  const pointer = crearSeguimientoPuntero();
  const bodyY = crearMuelle(0);
  const bodyRotation = crearMuelle(POSES[family].baseTilt);
  const hatY = crearMuelle(0);
  const hatRotation = crearMuelle(POSES[family].baseTilt);
  const transition = crearMuelle(0);

  fijarMuelle(bodyRotation, POSES[family].baseTilt);
  fijarMuelle(hatRotation, POSES[family].baseTilt);

  return {
    setFamily(next) {
      if (next === family) return;
      family = next;
      transitionAge = 0;
      transition.velocidad += 9;
    },
    setPointer(x, y) {
      pointer.apuntar(acotar(x, -1, 1), acotar(y, -1, 1));
    },
    clearPointer() {
      pointer.soltar();
    },
    advance(delta, now, rawVoice, signals, reduced) {
      if (reduced) return staticFrame(family);

      const dt = Number.isFinite(delta) ? acotar(delta, 0, 0.05) : 1 / 60;
      elapsed += dt;
      transitionAge += dt;
      const seconds = Number.isFinite(now) ? now / 1000 : elapsed;
      const voice = acotar(rawVoice, 0, 1);
      const adjustments = ajustesDe(signals, Number.isFinite(now) ? now : Date.now());

      const pointed = pointer.avanzar(dt);
      const targetLookX = pointed ? pointed.x * 8 : 0;
      const targetLookY = pointed ? pointed.y * 5 : 0;
      lookX = ease(lookX, targetLookX, dt, 0.045);
      lookY = ease(lookY, targetLookY, dt, 0.045);

      const idleFloat = Math.sin(seconds * Math.PI * 2 * 0.24) * 2.4;
      const happyJump =
        family === "contenta" && transitionAge < 0.62
          ? -22 * pulso(transitionAge / 0.62)
          : 0;
      const targetY = idleFloat + happyJump + adjustments.pulsoHabla * 1.5;
      const targetRotation =
        POSES[family].baseTilt +
        Math.sin(seconds * Math.PI * 2 * 0.17) * 1.3 +
        lookX * 0.16 +
        adjustments.inclinacionRemota * 0.35;

      avanzarMuelle(bodyY, targetY, dt, 180, 24);
      avanzarMuelle(bodyRotation, targetRotation, dt, 175, 23);
      avanzarMuelle(hatY, bodyY.valor, dt, 112, 15.5);
      avanzarMuelle(hatRotation, bodyRotation.valor, dt, 112, 15.5);
      avanzarMuelle(transition, 0, dt, 165, 13);

      const impulse = acotar(transition.valor, -1.4, 1.4);
      const flamePower = 0.08 + voice * 0.22 + adjustments.pulsoHabla * 0.12;
      const flameScale = [
        1 + Math.sin(seconds * Math.PI * 2 * 2.1) * flamePower,
        1 + Math.sin(seconds * Math.PI * 2 * 2.73 + 1.7) * flamePower,
        1 + Math.sin(seconds * Math.PI * 2 * 3.37 + 3.2) * flamePower,
      ] as const;

      return {
        body: transform(
          bodyY.valor,
          bodyRotation.valor - impulse * 4,
          1 - impulse * 0.07,
          1 + impulse * 0.09,
        ),
        hat: transform(
          hatY.valor - bodyY.valor,
          hatRotation.valor - bodyRotation.valor - impulse * 2.4,
        ),
        look: { x: lookX, y: lookY },
        blink: blinkAt(elapsed),
        flameScale,
        accessoryOpacity: 1,
        accessoryProgress: (seconds % 1.8) / 1.8,
        voice,
      };
    },
  };
}
