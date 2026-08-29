import type { FaceScene } from "../escena";
import type { FaceState } from "../estados";
import { SENALES_QUIETAS, type Senales } from "../modificadores";
import { COMPANION_GEOMETRY as G } from "./geometry";
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
  round:
    "M0 -16 C10 -16 16 -10 16 0 C16 10 10 16 0 16 " +
    "C-10 16 -16 10 -16 0 C-16 -10 -10 -16 0 -16 Z",
  dash: "M-25 -6 H25 V6 H-25 Z",
  chevron: "M-20 -22 L20 0 L-20 22 L-26 12 L2 0 L-26 -12 Z",
};

let sceneCounter = 0;

/** Adaptador estático inicial; el bucle físico se incorpora en la siguiente tarea. */
export function createCompanionScene(container: HTMLElement): FaceScene {
  const rig = createCompanionRig(`companion-vibi-${(sceneCounter += 1)}`);
  container.appendChild(rig.svg);

  let alive = true;
  let state: FaceState = "idle";
  let signals: Senales = SENALES_QUIETAS;

  const applyState = () => {
    const family = familyOf(state);
    const pose = POSES[family];
    rig.leftEye.setAttribute("d", EYES[pose.leftEye]);
    rig.rightEye.setAttribute("d", EYES[pose.rightEye]);
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
    const wave = rig.waveBars[0]?.parentElement;
    wave?.setAttribute("opacity", pose.accessory === "wave" ? "1" : "0");
    rig.svg.setAttribute("data-family", family);
    rig.svg.setAttribute("data-accessory", pose.accessory);
    rig.svg.setAttribute("data-signal-steps", String(signals.pasos));
  };

  applyState();

  return {
    setState(next) {
      if (!alive) return;
      state = next;
      applyState();
    },
    setSenales(next) {
      if (!alive) return;
      signals = next;
    },
    setPointer() {},
    clearPointer() {},
    dibujar() {},
    resize() {},
    dispose() {
      if (!alive) return;
      alive = false;
      rig.svg.remove();
    },
  };
}
