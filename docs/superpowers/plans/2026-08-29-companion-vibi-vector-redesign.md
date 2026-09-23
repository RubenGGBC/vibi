# Companion Vibi Vector Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the local companion's discarded cylindrical mascot with a faithful, reactive SVG rig based on the user's eight-face Vibi reference while leaving every web face unchanged.

**Architecture:** Keep the public `VibiFace`/`FaceScene` contract and route only `perfil === "companion"` into a new engine under `frontend/src/lib/face/companion/`. The new engine separates state-family mapping, fixed vector geometry, DOM rig construction, and time-based motion so the master silhouette can be calibrated before animation is layered on top.

**Tech Stack:** TypeScript 6, SVG DOM, React 19 lifecycle integration, Vitest/jsdom, Vite/Tauri companion build, existing spring and voice helpers.

**Spec:** `docs/superpowers/specs/2026-08-29-companion-vibi-vector-redesign-design.md`

## Global Constraints

- Change only the local companion visual selected by `perfil === "companion"`; the web and rail faces must remain unchanged.
- Keep the existing `VibiFace` props and `FaceScene` methods unchanged.
- Use one master silhouette with exactly eight initial visual families: reposo, recelo, contenta, trabajando, duda, hablando, ejecutando, buscando.
- Map every current `ESTADOS` member to one of those eight families; unknown runtime values fall back to reposo.
- The master silhouette must use a tilted asymmetric head, crescent jaw, dominant tapered top hat, broad diagonal brim, and exactly three readable side flames.
- Add no runtime dependency; use the existing SVG DOM, `faceMotion.ts`, `modificadores.ts`, and `oido.ts` helpers.
- Respect `prefers-reduced-motion` with stable, readable poses.
- Preserve all unrelated dirty-worktree changes and commit only task-owned paths.

## File Map

- Create `frontend/src/lib/face/companion/states.ts`: eight-family type, complete state mapping, family pose metadata.
- Create `frontend/src/lib/face/companion/states.test.ts`: coverage and semantic mapping tests.
- Create `frontend/src/lib/face/companion/geometry.ts`: canonical view box, Bézier paths, anchors, gradients, and landmarks.
- Create `frontend/src/lib/face/companion/rig.ts`: construct the SVG DOM once and expose typed element handles.
- Create `frontend/src/lib/face/companion/rig.test.ts`: structural and reference-landmark tests.
- Create `frontend/src/lib/face/companion/motion.ts`: deterministic springs, blink, flame, pointer, transition, and reduced-motion frame calculation.
- Create `frontend/src/lib/face/companion/motion.test.ts`: time-based behavior tests without DOM.
- Create `frontend/src/lib/face/companion/scene.ts`: `FaceScene` adapter, render loop, live signals, and disposal.
- Create `frontend/src/lib/face/companion/scene.test.ts`: scene, input, and lifecycle tests.
- Modify `frontend/src/components/VibiFace.tsx`: select the new scene for companion and add a profile-specific CSS hook without changing props or lifecycle.
- Modify `frontend/src/components/VibiFace.test.tsx`: prove the hook and unchanged public behavior.
- Modify `frontend/src/styles/companion.css`: size/overflow and reduced-motion integration for the new rig.
- Create `frontend/companion-face-review.html`: development-only eight-state comparison surface.
- Create `frontend/src/companionFaceReview.ts`: mount and freeze the eight representative states.
- Create `frontend/src/styles/companion-face-review.css`: fixed comparison grid.
- Add `docs/superpowers/assets/2026-08-29-vibi-eight-faces-reference.png`: stable copy of the user-provided reference used by the comparison surface.

---

### Task 1: Define the eight-family vocabulary and total state mapping

**Files:**
- Create: `frontend/src/lib/face/companion/states.test.ts`
- Create: `frontend/src/lib/face/companion/states.ts`

**Interfaces:**
- Consumes: `FaceState` and `ESTADOS` from `../estados`.
- Produces: `CompanionFamily`, `CompanionAccessory`, `CompanionPose`, `POSES`, `FAMILY_BY_STATE`, and `familyOf(state: FaceState | string): CompanionFamily`.

- [ ] **Step 1: Write the failing mapping tests**

```ts
import { describe, expect, it } from "vitest";
import { ESTADOS } from "../estados";
import { FAMILY_BY_STATE, POSES, familyOf } from "./states";

describe("familias del companion", () => {
  it("cubre una vez todos los estados actuales", () => {
    expect(Object.keys(FAMILY_BY_STATE).sort()).toEqual([...ESTADOS].sort());
  });

  it("conserva las ocho familias aprobadas", () => {
    expect(new Set(Object.values(FAMILY_BY_STATE))).toEqual(new Set([
      "reposo", "recelo", "contenta", "trabajando",
      "duda", "hablando", "ejecutando", "buscando",
    ]));
    expect(Object.keys(POSES).sort()).toEqual([
      "buscando", "contenta", "duda", "ejecutando",
      "hablando", "recelo", "reposo", "trabajando",
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
```

- [ ] **Step 2: Run the tests and verify RED**

Run from `frontend`:

```powershell
npm test -- --run src/lib/face/companion/states.test.ts
```

Expected: FAIL because `./states` does not exist.

- [ ] **Step 3: Implement the complete mapping and pose contract**

```ts
import type { FaceState } from "../estados";

export type CompanionFamily =
  | "reposo" | "recelo" | "contenta" | "trabajando"
  | "duda" | "hablando" | "ejecutando" | "buscando";

export type CompanionAccessory = "none" | "question" | "wave" | "terminal" | "magnifier";
export type CompanionEye = "pill" | "suspicious-left" | "suspicious-right" | "happy" | "soft" | "round" | "dash" | "chevron";

export interface CompanionPose {
  leftEye: CompanionEye;
  rightEye: CompanionEye;
  accessory: CompanionAccessory;
  mouth: boolean;
  baseTilt: number;
}

export const POSES: Record<CompanionFamily, CompanionPose> = {
  reposo: { leftEye: "pill", rightEye: "pill", accessory: "none", mouth: false, baseTilt: -4 },
  recelo: { leftEye: "suspicious-left", rightEye: "suspicious-right", accessory: "none", mouth: false, baseTilt: -7 },
  contenta: { leftEye: "happy", rightEye: "happy", accessory: "none", mouth: false, baseTilt: -4 },
  trabajando: { leftEye: "soft", rightEye: "soft", accessory: "none", mouth: true, baseTilt: -3 },
  duda: { leftEye: "round", rightEye: "round", accessory: "question", mouth: false, baseTilt: 3 },
  hablando: { leftEye: "soft", rightEye: "soft", accessory: "wave", mouth: false, baseTilt: -2 },
  ejecutando: { leftEye: "dash", rightEye: "chevron", accessory: "terminal", mouth: false, baseTilt: -5 },
  buscando: { leftEye: "pill", rightEye: "pill", accessory: "magnifier", mouth: false, baseTilt: -4 },
};

export const FAMILY_BY_STATE: Record<FaceState, CompanionFamily> = {
  idle: "reposo", vigilando: "reposo", cambiando: "reposo", offline: "reposo",
  recelo: "recelo", denegada: "recelo", alert: "recelo", fallo: "recelo", perdida: "recelo",
  pleased: "contenta", logro: "contenta", vibing: "contenta",
  working: "trabajando", reading: "trabajando", writing: "trabajando", noting: "trabajando", trastienda: "trabajando",
  thinking: "duda", waiting: "duda", arranque: "duda", vinculando: "duda",
  listening: "hablando", speaking: "hablando",
  hacking: "ejecutando", handling: "ejecutando", launching: "ejecutando", sending: "ejecutando", reaching: "ejecutando",
  searching: "buscando", browsing: "buscando", rummaging: "buscando", peeking: "buscando",
};

export const familyOf = (state: FaceState | string): CompanionFamily =>
  FAMILY_BY_STATE[state as FaceState] ?? "reposo";
```

- [ ] **Step 4: Run the tests and verify GREEN**

```powershell
npm test -- --run src/lib/face/companion/states.test.ts
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit only the mapping**

```powershell
git add -- frontend/src/lib/face/companion/states.ts frontend/src/lib/face/companion/states.test.ts
git commit -m "feat(companion): define Vibi face families"
```

---

### Task 2: Build the faithful static master rig

**Files:**
- Create: `frontend/src/lib/face/companion/geometry.ts`
- Create: `frontend/src/lib/face/companion/rig.ts`
- Create: `frontend/src/lib/face/companion/rig.test.ts`

**Interfaces:**
- Consumes: no previous runtime module; geometry is fixed data.
- Produces: `COMPANION_VIEWBOX`, `COMPANION_GEOMETRY`, `REFERENCE_LANDMARKS`, `CompanionRig`, and `createCompanionRig(uid: string): CompanionRig`.

- [ ] **Step 1: Write a failing structural test for the master silhouette**

```ts
import { describe, expect, it } from "vitest";
import { REFERENCE_LANDMARKS } from "./geometry";
import { createCompanionRig } from "./rig";

describe("rig vectorial del companion", () => {
  it("monta la silueta de la referencia en seis grupos", () => {
    const rig = createCompanionRig("test");
    expect(rig.svg.getAttribute("viewBox")).toBe("0 0 420 360");
    for (const name of ["hat", "face", "jaw", "eyes", "flame", "accessories"]) {
      expect(rig.svg.querySelector(`[data-vibi-part='${name}']`)).not.toBeNull();
    }
    expect(rig.flameTongues).toHaveLength(3);
  });

  it("mantiene la diagonal y las proporciones dominantes", () => {
    expect(REFERENCE_LANDMARKS.hatTop).toEqual({ x: 96, y: 28 });
    expect(REFERENCE_LANDMARKS.brimLeft).toEqual({ x: 38, y: 174 });
    expect(REFERENCE_LANDMARKS.brimRight).toEqual({ x: 342, y: 112 });
    expect(REFERENCE_LANDMARKS.jawTip).toEqual({ x: 178, y: 299 });
    expect(REFERENCE_LANDMARKS.flameTip).toEqual({ x: 369, y: 151 });
  });

  it("crea gradientes y recortes con ids aislados por escena", () => {
    const a = createCompanionRig("a");
    const b = createCompanionRig("b");
    expect(a.svg.innerHTML).toContain("url(#a-hat-gradient)");
    expect(b.svg.innerHTML).toContain("url(#b-hat-gradient)");
    expect(a.svg.innerHTML).not.toContain("url(#b-");
  });
});
```

- [ ] **Step 2: Run the rig test and verify RED**

```powershell
npm test -- --run src/lib/face/companion/rig.test.ts
```

Expected: FAIL because `geometry.ts` and `rig.ts` do not exist.

- [ ] **Step 3: Add the canonical geometry**

Use one `0 0 420 360` coordinate system and export fixed paths. These initial
paths deliberately encode the reference's lean and are the only values tuned
during the later visual-calibration task:

```ts
export const COMPANION_VIEWBOX = "0 0 420 360";

export const REFERENCE_LANDMARKS = {
  hatTop: { x: 96, y: 28 },
  brimLeft: { x: 38, y: 174 },
  brimRight: { x: 342, y: 112 },
  jawTip: { x: 178, y: 299 },
  flameTip: { x: 369, y: 151 },
} as const;

export const COMPANION_GEOMETRY = {
  crown: "M96 28 C75 30 62 42 69 58 L108 162 C154 154 211 138 260 119 L244 42 C240 25 226 18 204 20 Z",
  crownFoldA: "M128 48 C139 80 145 116 147 151",
  crownFoldB: "M151 41 C159 78 164 111 165 145",
  brim: "M38 174 C24 154 39 136 69 137 C120 151 193 132 267 101 C296 89 326 91 342 112 C314 142 272 167 221 186 C150 212 76 207 38 174 Z",
  head: "M89 171 C126 151 194 145 254 157 C299 166 322 194 314 229 C304 268 255 290 191 300 C145 307 100 283 79 247 C62 218 64 185 89 171 Z",
  mask: "M61 156 C136 132 251 134 326 169 L320 233 C289 222 260 230 231 242 C195 258 156 250 124 233 C102 221 81 215 67 220 Z",
  jaw: "M77 222 C99 222 120 237 145 248 C180 264 218 263 254 248 C276 239 296 235 314 238 C296 270 252 291 191 300 C143 306 98 281 77 246 Z",
  mouth: "M135 236 C160 251 188 250 212 230",
  question: "M326 79 C349 69 369 79 368 98 C367 112 350 116 347 131 M344 148 L344 149",
  terminalDash: "M128 218 L167 218",
  terminalChevron: "M211 198 L238 218 L211 238",
  magnifierRing: { cx: 329, cy: 248, r: 25 },
  magnifierHandle: "M347 267 L373 293",
  flameTongues: [
    { outer: "M303 231 C311 204 307 183 327 165 C325 188 346 193 339 216 C334 234 317 246 303 231 Z", inner: "M317 225 C323 210 321 199 331 188 C330 202 340 207 335 220 C331 230 323 233 317 225 Z" },
    { outer: "M325 194 C335 169 337 145 357 126 C352 151 374 156 367 178 C362 195 344 207 325 194 Z", inner: "M341 185 C347 171 347 159 357 148 C355 163 365 168 360 179 C356 188 348 191 341 185 Z" },
    { outer: "M348 165 C357 145 358 128 375 114 C372 133 389 137 383 154 C378 166 365 175 348 165 Z", inner: "M361 158 C366 148 366 140 374 132 C373 142 380 146 376 154 C373 160 367 162 361 158 Z" },
  ],
  eyeAnchors: [{ x: 142, y: 217 }, { x: 213, y: 205 }],
} as const;
```

- [ ] **Step 4: Construct the SVG once and return typed handles**

`createCompanionRig` must:

1. create an SVG with classes `vibi-svg companion-vibi-svg`;
2. add `<defs>` containing `hat-gradient`, `flame-gradient`, and a head clip path using the supplied `uid`;
3. append groups in this exact paint order: crown, head/mask/jaw, flames, brim, eyes/mouth, accessories;
4. set `data-vibi-part` on the six public groups;
5. create exactly three `.companion-vibi-flame-tongue` groups, each with its outer and inner path;
6. expose handles through this exact interface:

```ts
export interface CompanionRig {
  svg: SVGSVGElement;
  body: SVGGElement;
  hat: SVGGElement;
  leftEye: SVGPathElement;
  rightEye: SVGPathElement;
  mouth: SVGPathElement;
  flameTongues: SVGGElement[];
  question: SVGGElement;
  waveBars: SVGRectElement[];
  terminal: SVGGElement;
  magnifier: SVGGElement;
}
```

Set the hat fill to `url(#${uid}-hat-gradient)`, the outer flame fills to
`url(#${uid}-flame-gradient)`, the mask to `var(--companion-vibi-black)`, and
the jaw/eyes/inner flames to `var(--companion-vibi-white)`.

- [ ] **Step 5: Run the rig tests and verify GREEN**

```powershell
npm test -- --run src/lib/face/companion/rig.test.ts
```

Expected: 3 tests PASS.

- [ ] **Step 6: Commit the static master**

```powershell
git add -- frontend/src/lib/face/companion/geometry.ts frontend/src/lib/face/companion/rig.ts frontend/src/lib/face/companion/rig.test.ts
git commit -m "feat(companion): draw Vibi master rig"
```

---

### Task 3: Route only the companion to the new static scene

**Files:**
- Create: `frontend/src/lib/face/companion/scene.ts`
- Create: `frontend/src/lib/face/companion/scene.test.ts`
- Modify: `frontend/src/components/VibiFace.tsx:88`
- Modify: `frontend/src/components/VibiFace.test.tsx`

**Interfaces:**
- Consumes: `createCompanionRig`, `familyOf`, `POSES`, current `FaceScene`, and `Senales`.
- Produces: `createCompanionScene(container: HTMLElement): FaceScene`; `VibiFace` selects it only for companion while `crearEscenaCara` remains untouched for web.

- [ ] **Step 1: Write failing profile-isolation tests**

Extend the hoisted mocks in `VibiFace.test.tsx` and mock the new module:

```ts
const mocks = vi.hoisted(() => ({
  crearEscenaCara: vi.fn(),
  createCompanionScene: vi.fn(),
}));

vi.mock("../lib/face/companion/scene", () => ({
  createCompanionScene: mocks.createCompanionScene,
}));

beforeEach(() => {
  mocks.crearEscenaCara.mockReset();
  mocks.createCompanionScene.mockReset();
});
```

Then add:

```ts
it("expone un hook visual únicamente para el perfil companion", () => {
  mocks.createCompanionScene.mockReturnValue(escenaFalsa());
  mocks.crearEscenaCara.mockReturnValue(escenaFalsa());
  const { container, rerender } = render(<VibiFace state="idle" perfil="companion" />);
  expect(container.querySelector(".face-canvas-companion")).not.toBeNull();
  expect(mocks.createCompanionScene).toHaveBeenCalledTimes(1);
  expect(mocks.crearEscenaCara).not.toHaveBeenCalled();
  rerender(<VibiFace state="idle" perfil="web" />);
  expect(container.querySelector(".face-canvas-companion")).toBeNull();
  expect(mocks.crearEscenaCara).toHaveBeenCalledTimes(1);
});
```

Create `scene.test.ts` with the scene's first real behavior:

```ts
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
```

- [ ] **Step 2: Run both files and verify RED**

```powershell
npm test -- --run src/lib/face/companion/scene.test.ts src/components/VibiFace.test.tsx
```

Expected: FAIL because `scene.ts` does not exist, `VibiFace` does not select it, and the CSS hook is absent.

- [ ] **Step 3: Implement a static `FaceScene` adapter**

`createCompanionScene` must append the rig, start in reposo, update eye paths and
accessory visibility in `setState`, accept but not yet animate signals/pointer,
and remove its SVG in `dispose`. Use a local `disposed` boolean so calls after
disposal are no-ops. Its `dibujar` and `resize` are no-ops in this task.

Use these initial closed path shapes so every family is legible before motion:

```ts
const EYES: Record<CompanionEye, string> = {
  pill: "M-9 -17 C-3 -22 7 -19 10 -11 L11 10 C8 20 -3 23 -9 16 C-12 8 -13 -8 -9 -17 Z",
  "suspicious-left": "M-28 -12 L22 3 L14 18 L-24 5 Z",
  "suspicious-right": "M-22 3 L28 -12 L24 5 L-14 18 Z",
  happy: "M-24 8 C-11 -10 10 -10 24 8 L16 15 C6 4 -6 4 -16 15 Z",
  soft: "M-23 -3 C-10 12 10 12 23 -3 L17 -10 C7 0 -7 0 -17 -10 Z",
  round: "M0 -16 C10 -16 16 -10 16 0 C16 10 10 16 0 16 C-10 16 -16 10 -16 0 C-16 -10 -10 -16 0 -16 Z",
  dash: "M-25 -6 H25 V6 H-25 Z",
  chevron: "M-20 -22 L20 0 L-20 22 L-26 12 L2 0 L-26 -12 Z",
};
```

- [ ] **Step 4: Select the companion scene and add its class hook in React**

Import `createCompanionScene` directly in `VibiFace.tsx`. Replace scene creation
with:

```ts
const scene = perfil === "companion"
  ? createCompanionScene(container)
  : crearEscenaCara(container, { perfil: "web" });
```

This deliberately avoids editing the already-dirty `escena.ts`; that complete
existing engine stays byte-for-byte unchanged and continues to serve web.

Change only the rendered span:

Change only the rendered span:

```tsx
return (
  <span
    className={`face-canvas${perfil === "companion" ? " face-canvas-companion" : ""}`}
    ref={containerRef}
    aria-hidden="true"
  />
);
```

- [ ] **Step 5: Run focused and existing face tests**

```powershell
npm test -- --run src/lib/face/companion/scene.test.ts src/components/VibiFace.test.tsx src/lib/face/escena.test.ts
```

Expected: all tests PASS; the web assertion still sees the pre-existing `.vibi-svg`.

- [ ] **Step 6: Commit the isolated routing**

```powershell
git add -- frontend/src/lib/face/companion/scene.ts frontend/src/lib/face/companion/scene.test.ts frontend/src/components/VibiFace.tsx frontend/src/components/VibiFace.test.tsx
git commit -m "feat(companion): isolate the new Vibi scene"
```

---

### Task 4: Implement deterministic physical motion

**Files:**
- Create: `frontend/src/lib/face/companion/motion.ts`
- Create: `frontend/src/lib/face/companion/motion.test.ts`

**Interfaces:**
- Consumes: `CompanionFamily`, `POSES`, `Senales`, `ajustesDe`, and the existing `crearMuelle`, `avanzarMuelle`, `fijarMuelle`, `crearSeguimientoPuntero`, `acotar`, `pulso`.
- Produces: `CompanionFrame` and `createCompanionMotion(initial?: CompanionFamily): CompanionMotion`.

- [ ] **Step 1: Write failing pure-motion tests**

```ts
import { describe, expect, it } from "vitest";
import { SENALES_QUIETAS } from "../modificadores";
import { createCompanionMotion } from "./motion";

describe("movimiento del companion", () => {
  it("mantiene viva la llama y retrasa la chistera", () => {
    const motion = createCompanionMotion("reposo");
    const a = motion.advance(1 / 60, 1000, 0, SENALES_QUIETAS, false);
    const b = motion.advance(1 / 60, 1200, 0, SENALES_QUIETAS, false);
    expect(b.flameScale).not.toEqual(a.flameScale);
    expect(b.hat.rotation).not.toBe(b.body.rotation);
  });

  it("hace anticipación y salto al entrar en contenta", () => {
    const motion = createCompanionMotion("reposo");
    motion.setFamily("contenta");
    const first = motion.advance(1 / 60, 1000, 0, SENALES_QUIETAS, false);
    let highest = first.body.y;
    for (let i = 1; i < 45; i += 1) {
      highest = Math.min(highest, motion.advance(1 / 60, 1000 + i * 16.67, 0, SENALES_QUIETAS, false).body.y);
    }
    expect(first.body.scaleY).not.toBeCloseTo(1, 3);
    expect(highest).toBeLessThan(-8);
  });

  it("lleva la mirada al puntero y después la suelta", () => {
    const motion = createCompanionMotion("reposo");
    motion.setPointer(1, -1);
    const pointed = motion.advance(0.1, 1000, 0, SENALES_QUIETAS, false);
    expect(pointed.look.x).toBeGreaterThan(0);
    expect(pointed.look.y).toBeLessThan(0);
    motion.clearPointer();
    const released = motion.advance(0.5, 1500, 0, SENALES_QUIETAS, false);
    expect(Math.abs(released.look.x)).toBeLessThan(Math.abs(pointed.look.x));
  });

  it("con movimiento reducido devuelve una pose estable", () => {
    const motion = createCompanionMotion("contenta");
    const a = motion.advance(1 / 60, 1000, 1, SENALES_QUIETAS, true);
    const b = motion.advance(1 / 60, 5000, 0, SENALES_QUIETAS, true);
    expect(b).toEqual(a);
  });
});
```

- [ ] **Step 2: Run the motion test and verify RED**

```powershell
npm test -- --run src/lib/face/companion/motion.test.ts
```

Expected: FAIL because `motion.ts` does not exist.

- [ ] **Step 3: Implement the frame contract and motion engine**

Use these exact public types:

```ts
export interface CompanionTransform {
  x: number; y: number; rotation: number; scaleX: number; scaleY: number;
}

export interface CompanionFrame {
  body: CompanionTransform;
  hat: CompanionTransform;
  look: { x: number; y: number };
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
  advance(delta: number, now: number, voice: number, signals: Senales, reduced: boolean): CompanionFrame;
}
```

Implementation rules:

- clamp `delta` to `0..0.05`;
- use one spring for body Y, body rotation, hat Y, hat rotation, and transition impulse;
- on a family change add `9` to transition velocity and reset transition age;
- make contenta jump with `-22 * pulso(age / 0.62)` during its first `0.62s`;
- calculate pointer look as `x * 8`, `y * 5` and ease it with a `0.045s` exponential time constant;
- blink for `0.13s` after deterministic waits of `2.8s`, `4.1s`, `3.3s`, then repeat;
- calculate the three flame scales with frequencies `2.1`, `2.73`, and `3.37`, phase offsets `0`, `1.7`, and `3.2`, plus `voice * 0.22`;
- make the hat spring use 70% of the body's stiffness so it visibly arrives late;
- when `reduced` is true, return a cached frame with the pose's `baseTilt`, look `{0,0}`, blink `1`, flame scales `[1,1,1]`, and no transition.

- [ ] **Step 4: Run the motion tests and verify GREEN**

```powershell
npm test -- --run src/lib/face/companion/motion.test.ts
```

Expected: 4 tests PASS without fake timers.

- [ ] **Step 5: Commit the pure motion engine**

```powershell
git add -- frontend/src/lib/face/companion/motion.ts frontend/src/lib/face/companion/motion.test.ts
git commit -m "feat(companion): animate Vibi with physical motion"
```

---

### Task 5: Render all eight families and reactive accessories

**Files:**
- Modify: `frontend/src/lib/face/companion/scene.ts`
- Modify: `frontend/src/lib/face/companion/scene.test.ts`
- Modify: `frontend/src/lib/face/companion/rig.ts`
- Modify: `frontend/src/lib/face/companion/rig.test.ts`

**Interfaces:**
- Consumes: `POSES`, `CompanionFrame`, `CompanionRig`, `EYES`, `nivelDeVoz`.
- Produces: eight visually distinct DOM states while preserving one body rig.

- [ ] **Step 1: Write failing family-render tests**

```ts
it.each([
  ["idle", "reposo", "none"],
  ["recelo", "recelo", "none"],
  ["pleased", "contenta", "none"],
  ["working", "trabajando", "none"],
  ["thinking", "duda", "question"],
  ["speaking", "hablando", "wave"],
  ["hacking", "ejecutando", "terminal"],
  ["searching", "buscando", "magnifier"],
] as const)("%s representa la familia %s", (state, family, accessory) => {
  const container = document.createElement("div");
  const scene = createCompanionScene(container);
  scene.setState(state);
  for (let i = 0; i < 30; i += 1) scene.dibujar(1 / 60);
  const svg = container.querySelector(".companion-vibi-svg")!;
  expect(svg.getAttribute("data-family")).toBe(family);
  expect(svg.getAttribute("data-accessory")).toBe(accessory);
  scene.dispose();
});

it("no sustituye la figura maestra al cambiar de familia", () => {
  const container = document.createElement("div");
  const scene = createCompanionScene(container);
  const head = container.querySelector("[data-vibi-part='face']");
  for (const state of ["recelo", "pleased", "working", "thinking", "speaking", "hacking", "searching"] as const) {
    scene.setState(state);
    scene.dibujar(1 / 60);
    expect(container.querySelector("[data-vibi-part='face']")).toBe(head);
  }
  scene.dispose();
});
```

- [ ] **Step 2: Run the scene test and verify RED**

```powershell
npm test -- --run src/lib/face/companion/scene.test.ts
```

Expected: FAIL because the static adapter does not expose family/accessory state or apply motion frames.

- [ ] **Step 3: Apply a frame to the rig**

Add pure formatting helpers inside `scene.ts`:

```ts
const transform = ({ x, y, rotation, scaleX, scaleY }: CompanionTransform, px: number, py: number) =>
  `translate(${x.toFixed(2)} ${y.toFixed(2)}) translate(${px} ${py}) rotate(${rotation.toFixed(2)}) scale(${scaleX.toFixed(4)} ${scaleY.toFixed(4)}) translate(${-px} ${-py})`;
```

On each `dibujar(delta)`:

- request a frame from motion using `performance.now()`, `nivelDeVoz()`, current signals, and the reduced-motion flag;
- apply body transform around `(190, 240)` and hat transform around `(168, 160)`;
- translate both eyes by frame look and scale Y by frame blink;
- scale each flame tongue around its base using the corresponding `flameScale` entry;
- show only the current pose accessory;
- set `data-family` and `data-accessory` on the SVG;
- animate the question vertically by `-12 * accessoryProgress`;
- scale the five wave bars from `0.25` to `1.6` using `max(frame.voice, signals cadence normalization)`;
- translate the terminal group by `accessoryProgress * 8`;
- move the magnifier on `x = cos(progress * 2π) * 11`, `y = sin(progress * 2π) * 7` and add that offset to the eyes' look.

- [ ] **Step 4: Run all companion unit tests**

```powershell
npm test -- --run src/lib/face/companion
```

Expected: state, rig, motion, and scene suites PASS.

- [ ] **Step 5: Commit the eight rendered families**

```powershell
git add -- frontend/src/lib/face/companion/rig.ts frontend/src/lib/face/companion/rig.test.ts frontend/src/lib/face/companion/scene.ts frontend/src/lib/face/companion/scene.test.ts
git commit -m "feat(companion): render eight Vibi expressions"
```

---

### Task 6: Complete the live loop, inputs, and lifecycle

**Files:**
- Modify: `frontend/src/lib/face/companion/scene.ts`
- Modify: `frontend/src/lib/face/companion/scene.test.ts`

**Interfaces:**
- Consumes: the complete `CompanionMotion`, `nivelDeVoz`, `Senales`, and browser animation/media-query APIs.
- Produces: a production `FaceScene` that starts immediately, reacts to voice/pointer/signals, and cleans up completely.

- [ ] **Step 1: Write failing lifecycle and live-input tests**

Add the live-input imports at the top of `scene.test.ts`:

```ts
import { SENALES_QUIETAS } from "../modificadores";
import { callarOido, publicarNivelDeVoz } from "../oido";
```

Call `callarOido()` in the file's existing `afterEach` cleanup, then add:

```ts
it("dibuja de inmediato y limita deltas grandes", () => {
  const container = document.createElement("div");
  const scene = createCompanionScene(container);
  expect(container.querySelector(".companion-vibi-svg")?.innerHTML).not.toContain("NaN");
  scene.dibujar(9);
  expect(container.querySelector(".companion-vibi-svg")?.innerHTML).not.toContain("NaN");
  scene.dispose();
});

it("reacciona a voz, puntero y señales", () => {
  const container = document.createElement("div");
  const scene = createCompanionScene(container);
  scene.setState("speaking");
  publicarNivelDeVoz(0.18);
  scene.setPointer(1, -1);
  scene.setSenales({ ...SENALES_QUIETAS, cadencia: 30, pasos: 8 });
  scene.dibujar(0.1);
  expect(Number(container.querySelector(".companion-vibi-wave")?.getAttribute("data-level"))).toBeGreaterThan(0.5);
  expect(container.querySelector(".companion-vibi-eyes")?.getAttribute("transform")).toMatch(/translate\([^0]/);
  scene.dispose();
});

it("cancela el bucle y deja de escribir tras dispose", () => {
  const cancel = vi.spyOn(window, "cancelAnimationFrame");
  const container = document.createElement("div");
  const scene = createCompanionScene(container);
  scene.dispose();
  expect(cancel).toHaveBeenCalled();
  expect(container.querySelector("svg")).toBeNull();
  scene.setState("recelo");
  scene.dibujar(1 / 60);
  expect(container.querySelector("svg")).toBeNull();
});
```

- [ ] **Step 2: Run the scene tests and verify RED**

```powershell
npm test -- --run src/lib/face/companion/scene.test.ts
```

Expected: FAIL on loop cancellation and/or live data attributes.

- [ ] **Step 3: Implement the production loop**

Use `requestAnimationFrame`, draw synchronously once before scheduling it, and
cap every delta at `0.05s`. Use the existing 24fps idle / 60fps active cadence
policy, treating pointer activity and every family except reposo as active.
Read `window.matchMedia("(prefers-reduced-motion: reduce)")` once, subscribe to
its `change` event, and remove that listener in `dispose`.

`setState`, `setSenales`, `setPointer`, and `clearPointer` must be no-ops after
disposal. `dispose` must cancel the exact pending frame id and remove the SVG.

- [ ] **Step 4: Run scene and React lifecycle tests**

```powershell
npm test -- --run src/lib/face/companion/scene.test.ts src/components/VibiFace.test.tsx
```

Expected: all tests PASS and no unhandled timer warnings.

- [ ] **Step 5: Commit live behavior**

```powershell
git add -- frontend/src/lib/face/companion/scene.ts frontend/src/lib/face/companion/scene.test.ts
git commit -m "feat(companion): connect Vibi motion to live state"
```

---

### Task 7: Calibrate the reference visually and finish companion-only styling

**Files:**
- Add: `docs/superpowers/assets/2026-08-29-vibi-eight-faces-reference.png`
- Create: `frontend/companion-face-review.html`
- Create: `frontend/src/companionFaceReview.ts`
- Create: `frontend/src/styles/companion-face-review.css`
- Modify: `frontend/src/lib/face/companion/geometry.ts`
- Modify: `frontend/src/styles/companion.css`

**Interfaces:**
- Consumes: `createCompanionScene` and the eight representative `FaceState` values.
- Produces: a development-only comparison page at `/companion-face-review.html` and final companion-only visual tokens.

- [ ] **Step 1: Preserve the supplied reference in the repository**

Copy exactly:

```powershell
New-Item -ItemType Directory -Force 'docs\superpowers\assets'
Copy-Item -LiteralPath 'C:\Users\rebel\AppData\Local\Temp\codex-clipboard-ukSdET.png' -Destination 'docs\superpowers\assets\2026-08-29-vibi-eight-faces-reference.png'
```

Verify its dimensions are `1680 × 935` before continuing. If the temporary file
is no longer present, stop and ask the user to attach Image #1 again; do not
substitute Image #2 or an internet image.

- [ ] **Step 2: Write a failing review-surface smoke test**

Add to `scene.test.ts`:

```ts
it("permite congelar las ocho familias para revisión", () => {
  const representatives = ["idle", "recelo", "pleased", "working", "thinking", "speaking", "hacking", "searching"] as const;
  const families = representatives.map((state) => {
    const container = document.createElement("div");
    const scene = createCompanionScene(container, { frozen: true });
    scene.setState(state);
    scene.dibujar(1 / 60);
    const family = container.querySelector("svg")?.getAttribute("data-family");
    scene.dispose();
    return family;
  });
  expect(families).toEqual(["reposo", "recelo", "contenta", "trabajando", "duda", "hablando", "ejecutando", "buscando"]);
});
```

- [ ] **Step 3: Run the test and verify RED**

```powershell
npm test -- --run src/lib/face/companion/scene.test.ts
```

Expected: TypeScript/test failure because the `frozen` option is not accepted.

- [ ] **Step 4: Add deterministic review mode and the comparison page**

Extend creation with:

```ts
export interface CompanionSceneOptions { frozen?: boolean }
export function createCompanionScene(container: HTMLElement, options: CompanionSceneOptions = {}): FaceScene
```

When frozen, do not schedule RAF and use reduced/static frames while still
applying the requested family. The review entry mounts these representatives:

```ts
const CELLS = [
  ["Reposo", "idle"], ["Recelo", "recelo"], ["Contenta", "pleased"], ["Trabajando", "working"],
  ["Duda", "thinking"], ["Hablando", "speaking"], ["Ejecutando", "hacking"], ["Buscando", "searching"],
] as const;
```

Render the saved reference at the top and an equal `4 × 2` grid below it. Each
cell must use a `420 × 360` stage and call `createCompanionScene(stage, { frozen:
true })` before `setState` and `dibujar(1 / 60)`.

- [ ] **Step 5: Add companion-only visual tokens**

Add all new variables to `companion.css`, scoped to `.face-canvas-companion`:

```css
.face-canvas-companion {
  --companion-vibi-red: #ff0b13;
  --companion-vibi-deep-red: #a20712;
  --companion-vibi-black: #090310;
  --companion-vibi-white: #fff;
  --companion-vibi-glow: 99 28 135;
}

.face-canvas-companion .companion-vibi-figure {
  filter:
    drop-shadow(5px 7px 0 rgb(2 0 5 / 0.9))
    drop-shadow(0 0 24px rgb(var(--companion-vibi-glow) / 0.32));
}

.face-canvas-companion .companion-vibi-svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}
```

Do not edit `cara.css`; it is already dirty and remains the web visual source.

- [ ] **Step 6: Render and calibrate against Image #1 in this strict order**

Run:

```powershell
npm run dev:companion -- --host 127.0.0.1
```

Open `http://127.0.0.1:1420/companion-face-review.html`. Compare at 100% zoom
and adjust only `geometry.ts` plus companion-scoped filters until all checks
pass:

1. the brim rises from `(38,174)` toward `(342,112)` and is the dominant diagonal;
2. the crown occupies at least 55% of the figure height above the eyes and tapers toward its base;
3. the jaw is a crescent, its tip sits left of center, and the head is not circular/cylindrical;
4. the eyes remain secondary: each is below 12% of head width;
5. the three flame tips are separate at 100% zoom and do not merge into one white-red mass;
6. the rightmost silhouette stays inside x=395 and the hat top inside y=18 so glow is not clipped;
7. the 320px companion rendering still shows both crown folds, jaw tip, and three flames;
8. no state changes the fixed head, jaw, brim, or crown paths.

Use the Browser skill to take a full-page screenshot of the finished 4×2 sheet
and keep that screenshot in the turn for the final review. If no browser surface
is available, do not claim visual completion: ask the user to open the exact
local URL above and attach one screenshot of the full sheet.

- [ ] **Step 7: Run focused tests after calibration**

```powershell
npm test -- --run src/lib/face/companion src/lib/face/escena.test.ts src/components/VibiFace.test.tsx
```

Expected: all tests PASS after geometry changes.

- [ ] **Step 8: Commit the approved visual master and review surface**

```powershell
git add -- docs/superpowers/assets/2026-08-29-vibi-eight-faces-reference.png frontend/companion-face-review.html frontend/src/companionFaceReview.ts frontend/src/styles/companion-face-review.css frontend/src/lib/face/companion/geometry.ts frontend/src/styles/companion.css
git commit -m "feat(companion): match Vibi reference artwork"
```

---

### Task 8: Run full verification and document the finished first phase

**Files:**
- Modify: `docs/diario.md`
- Test: all companion and face files touched above.

**Interfaces:**
- Consumes: complete companion implementation.
- Produces: verified build and a concise project record; no new runtime API.

- [ ] **Step 1: Add a diary entry with concrete decisions**

At the top of `docs/diario.md`, add `## 2026-08-29 — Vibi vectorial en el
companion` recording: companion-only routing, one SVG master, eight-family
mapping, three live flames, physical hat lag, voice/pointer inputs, reduced
motion, and the exact verification commands/results from the following steps.

- [ ] **Step 2: Run the complete face test set**

```powershell
npm test -- --run src/lib/face src/components/VibiFace.test.tsx src/components/CompanionApp.test.tsx
```

Expected: all selected suites PASS with no unhandled errors or warnings.

- [ ] **Step 3: Run typechecking and the companion production build**

```powershell
npm run build:companion
```

Expected: both TypeScript checks and the Vite companion build exit 0.

- [ ] **Step 4: Run lint on every touched TypeScript file**

```powershell
npx eslint src/lib/face/companion src/components/VibiFace.tsx src/companionFaceReview.ts
```

Expected: exit 0 with no warnings.

- [ ] **Step 5: Inspect the final diff without disturbing unrelated work**

```powershell
git diff --check
git status --short
```

Confirm that every changed path belongs to this plan or was already dirty
before execution. Do not stage existing changes outside the task-owned paths.

- [ ] **Step 6: Commit the diary and any verification-only fixes**

```powershell
git add -- docs/diario.md
git commit -m "docs: record companion Vibi redesign"
```

- [ ] **Step 7: Present the visual sheet and verification evidence**

Show the Browser full-page screenshot of the review sheet to the user, report
the exact passing test/build counts, and explicitly state that the remaining
Vibi states currently inherit one of the eight approved families for later
gesture design. If Browser was unavailable, this handoff stays incomplete until
the user returns the requested screenshot and the visual comparison is reviewed.
