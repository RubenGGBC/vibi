import type { FaceScene } from "../escena";
import type { FaceState } from "../estados";
import { SENALES_QUIETAS, type Senales } from "../modificadores";
import { nivelDeVoz } from "../oido";
import { COMPANION_GEOMETRY as G } from "./geometry";
import { createCompanionMotion, type CompanionTransform } from "./motion";
import { createCompanionRig } from "./rig";
import { POSES, familyOf, type CompanionEye } from "./states";

const EYES: Record<CompanionEye, string> = {
  pill:
    "M-9 -17 C-3 -22 7 -19 10 -11 L11 10 " +
    "C8 20 -3 23 -9 16 C-12 8 -13 -8 -9 -17 Z",
  "suspicious-left": "M-28 -12 L22 3 L14 18 L-24 5 Z",
  "suspicious-right": "M-22 3 L28 -12 L24 5 L-14 18 Z",
  happy: "M-24 8 C-11 -10 10 -10 24 8 L16 15 C6 4 -6 4 -16 15 Z",
  soft: "M-23 -3 C-10 12 10 12 23 -3 L17 -10 C7 0 -7 0 -17 -10 Z",
  "crescent-left":
    "M-8 -15 C-20 -10 -21 7 -11 15 C-5 20 3 18 7 12 " +
    "C-2 14 -10 8 -10 0 C-10 -7 -5 -12 2 -16 C-2 -17 -5 -17 -8 -15 Z",
  "crescent-right":
    "M8 -15 C20 -10 21 7 11 15 C5 20 -3 18 -7 12 " +
    "C2 14 10 8 10 0 C10 -7 5 -12 -2 -16 C2 -17 5 -17 8 -15 Z",
  dash: "M-25 -6 H25 V6 H-25 Z",
  chevron: "M-20 -22 L20 0 L-20 22 L-26 12 L2 0 L-26 -12 Z",
};

let sceneCounter = 0;

const place = (value: CompanionTransform, pivotX: number, pivotY: number): string =>
  `translate(${value.x.toFixed(2)} ${value.y.toFixed(2)}) ` +
  `translate(${pivotX} ${pivotY}) rotate(${value.rotation.toFixed(2)}) ` +
  `scale(${value.scaleX.toFixed(4)} ${value.scaleY.toFixed(4)}) ` +
  `translate(${-pivotX} ${-pivotY})`;

const scaleAt = (x: number, y: number, scaleY: number): string =>
  `translate(${x} ${y}) scale(${(2 - scaleY).toFixed(4)} ${scaleY.toFixed(4)}) ` +
  `translate(${-x} ${-y})`;

const IDLE_CADENCE = 1 / 24;
const ACTIVE_CADENCE = 1 / 60;
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

export interface CompanionSceneOptions {
  frozen?: boolean;
}

export function createCompanionScene(
  container: HTMLElement,
  options: CompanionSceneOptions = {},
): FaceScene {
  const rig = createCompanionRig(`companion-vibi-${(sceneCounter += 1)}`);
  container.appendChild(rig.svg);

  let alive = true;
  let state: FaceState = "idle";
  let signals: Senales = SENALES_QUIETAS;
  let pointerActive = false;
  let frameCount = 0;
  let lastFrameTime = 0;
  let animationFrame = 0;
  const motion = createCompanionMotion("reposo");
  const motionPreference =
    !options.frozen && typeof window.matchMedia === "function"
      ? window.matchMedia(REDUCED_MOTION_QUERY)
      : null;
  let reducedMotion = options.frozen || (motionPreference?.matches ?? false);

  const onMotionPreferenceChange = (event: MediaQueryListEvent) => {
    reducedMotion = event.matches;
  };
  motionPreference?.addEventListener?.("change", onMotionPreferenceChange);

  const applyState = () => {
    const family = familyOf(state);
    const pose = POSES[family];
    rig.leftEye.setAttribute(
      "d",
      pose.leftEye === "pill" ? G.pillEyes[0] : EYES[pose.leftEye],
    );
    rig.rightEye.setAttribute(
      "d",
      pose.rightEye === "pill" ? G.pillEyes[1] : EYES[pose.rightEye],
    );
    const terminalEyes = pose.accessory === "terminal";
    rig.leftEye.setAttribute("opacity", terminalEyes ? "0" : "1");
    rig.rightEye.setAttribute("opacity", terminalEyes ? "0" : "1");
    rig.leftEye.setAttribute(
      "transform",
      `translate(${G.eyeAnchors[0].x} ${G.eyeAnchors[0].y})`,
    );
    rig.rightEye.setAttribute(
      "transform",
      `translate(${G.eyeAnchors[1].x} ${G.eyeAnchors[1].y})`,
    );
    rig.mouth.setAttribute("opacity", pose.mouth ? "1" : "0");
    rig.question.setAttribute("opacity", pose.accessory === "question" ? "1" : "0");
    rig.terminal.setAttribute("opacity", pose.accessory === "terminal" ? "1" : "0");
    rig.magnifier.setAttribute("opacity", pose.accessory === "magnifier" ? "1" : "0");
    rig.wave.setAttribute("opacity", pose.accessory === "wave" ? "1" : "0");
    rig.svg.setAttribute("data-family", family);
    rig.svg.setAttribute("data-accessory", pose.accessory);
    rig.svg.setAttribute("data-signal-steps", String(signals.pasos));
  };

  const draw = (delta: number) => {
    if (!alive) return;
    const step = Number.isFinite(delta) ? Math.min(Math.max(delta, 0), 0.05) : 1 / 60;
    const frame = motion.advance(
      step,
      performance.now(),
      nivelDeVoz(),
      signals,
      reducedMotion,
    );
    const pose = POSES[familyOf(state)];

    rig.body.setAttribute("transform", place(frame.body, 190, 240));
    rig.hat.setAttribute("transform", place(frame.hat, 168, 160));

    let lookX = frame.look.x;
    let lookY = frame.look.y;
    if (pose.accessory === "magnifier") {
      const angle = frame.accessoryProgress * Math.PI * 2;
      lookX += Math.cos(angle) * 4;
      lookY += Math.sin(angle) * 2.5;
    }
    rig.leftEye.setAttribute(
      "transform",
      `translate(${(G.eyeAnchors[0].x + lookX).toFixed(2)} ` +
        `${(G.eyeAnchors[0].y + lookY).toFixed(2)}) scale(1 ${frame.blink.toFixed(4)})`,
    );
    rig.rightEye.setAttribute(
      "transform",
      `translate(${(G.eyeAnchors[1].x + lookX).toFixed(2)} ` +
        `${(G.eyeAnchors[1].y + lookY).toFixed(2)}) scale(1 ${frame.blink.toFixed(4)})`,
    );

    rig.flameTongues.forEach((tongue, index) => {
      const base = G.flameBases[index];
      tongue.setAttribute("transform", scaleAt(base.x, base.y, frame.flameScale[index]));
    });

    rig.question.setAttribute(
      "transform",
      `translate(0 ${(-12 * frame.accessoryProgress).toFixed(2)})`,
    );
    const liveLevel = Math.max(
      pose.accessory === "wave" ? 0.55 : 0,
      frame.voice,
      Math.min(1, signals.cadencia / 40),
    );
    rig.wave.setAttribute("data-level", liveLevel.toFixed(3));
    rig.waveBars.forEach((bar, index) => {
      const scale = Math.min(
        1.6,
        0.25 + liveLevel * 1.1 + Math.sin(frame.accessoryProgress * 10 + index) * 0.12,
      );
      const x = 289.5 + index * 17;
      bar.setAttribute(
        "transform",
        `translate(${x} 291) scale(1 ${scale.toFixed(3)}) translate(${-x} -291)`,
      );
    });
    rig.terminal.setAttribute(
      "transform",
      `translate(${(frame.accessoryProgress * 8).toFixed(2)} 0)`,
    );
    const angle = frame.accessoryProgress * Math.PI * 2;
    rig.magnifier.setAttribute(
      "transform",
      `translate(${(Math.cos(angle) * 11).toFixed(2)} ${(Math.sin(angle) * 7).toFixed(2)})`,
    );

    frameCount += 1;
    rig.svg.setAttribute("data-frame", String(frameCount));
  };

  const loop = (timestamp: number) => {
    if (!alive) return;
    animationFrame = window.requestAnimationFrame(loop);
    const time = timestamp / 1000;
    const delta = lastFrameTime ? time - lastFrameTime : 1 / 60;
    const active = pointerActive || familyOf(state) !== "reposo";
    const cadence = active ? ACTIVE_CADENCE : IDLE_CADENCE;
    if (delta < cadence) return;
    lastFrameTime = time;
    draw(delta);
  };

  applyState();
  draw(1 / 60);
  if (!options.frozen) animationFrame = window.requestAnimationFrame(loop);

  return {
    setState(next) {
      if (!alive) return;
      state = next;
      motion.setFamily(familyOf(next));
      applyState();
    },
    setSenales(next) {
      if (!alive) return;
      signals = next;
      rig.svg.setAttribute("data-signal-steps", String(signals.pasos));
    },
    setPointer(x, y) {
      if (!alive) return;
      pointerActive = true;
      motion.setPointer(x, y);
    },
    clearPointer() {
      if (!alive) return;
      pointerActive = false;
      motion.clearPointer();
    },
    dibujar: draw,
    resize() {},
    dispose() {
      if (!alive) return;
      alive = false;
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      motionPreference?.removeEventListener?.("change", onMotionPreferenceChange);
      rig.svg.remove();
    },
  };
}
