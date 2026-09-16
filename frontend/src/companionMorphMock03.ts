import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";

import { createCompanionScene } from "./lib/face/companion/scene";
import type { FaceState } from "./lib/face/estados";
import "./styles/companion.css";
import "./styles/companion-morphs.css";
import "./styles/companion-morph-mock.css";
import "./styles/companion-morph-mock-03.css";

interface Scenario {
  id: "pen" | "note" | "camera";
  number: string;
  title: string;
  state: FaceState;
  result: string;
  description: string;
  visual: string;
}

const penVisual = `
  <g class="morph-object morph-pen">
    <g class="pen-shape" transform="rotate(-35 210 190)">
      <path class="pen-shadow" d="M63 154 Q63 126 92 126 H326 Q354 126 354 154 V226 Q354 254 326 254 H92 Q63 254 63 226 Z" />
      <path class="pen-body" d="M89 132 H326 Q348 132 348 154 V226 Q348 248 326 248 H89 Z" />
      <path class="pen-nib" d="M89 132 L34 190 L89 248 Z" />
      <path class="pen-nib-core" d="M55 190 H89" />
      <path class="pen-cap" d="M304 132 H338 Q355 132 355 150 V230 Q355 248 338 248 H304 Z" />
      <g class="morph-eyes pen-eyes">
        <rect x="151" y="161" width="20" height="47" rx="10" />
        <path d="M198 177 C211 193 229 193 242 177 L234 165 C224 177 215 177 206 165 Z" />
      </g>
      <g class="pen-ink-lines">
        <path d="M119 224 H182 M253 215 H284" />
      </g>
    </g>
    <path class="pen-writing-line" d="M75 306 C151 327 244 326 344 292" />
  </g>
`;

const noteVisual = `
  <g class="morph-object morph-note-object">
    <path class="note-shadow" d="M85 58 H326 Q348 58 348 80 V277 L287 338 H85 Q63 338 63 316 V80 Q63 58 85 58 Z" />
    <path class="note-sheet" d="M85 58 H326 Q348 58 348 80 V277 L287 338 H85 Q63 338 63 316 V80 Q63 58 85 58 Z" />
    <path class="note-fold" d="M287 338 V292 Q287 277 303 277 H348" />
    <path class="note-rule note-rule-red" d="M103 116 H302" />
    <g class="morph-eyes note-eyes">
      <rect x="139" y="153" width="20" height="48" rx="10" />
      <rect x="197" y="149" width="20" height="48" rx="10" />
    </g>
    <g class="note-rules">
      <path d="M104 232 H302 M104 258 H275 M104 284 H240" />
    </g>
    <circle class="note-pin" cx="303" cy="91" r="12" />
  </g>
`;

const cameraVisual = `
  <g class="morph-object morph-camera">
    <path class="camera-shadow" d="M70 125 H126 L149 91 H257 L280 125 H350 Q371 125 371 147 V294 Q371 316 349 316 H71 Q49 316 49 294 V147 Q49 125 70 125 Z" />
    <path class="camera-shell" d="M70 125 H126 L149 91 H257 L280 125 H350 Q371 125 371 147 V294 Q371 316 349 316 H71 Q49 316 49 294 V147 Q49 125 70 125 Z" />
    <circle class="camera-lens-rim" cx="210" cy="221" r="88" />
    <circle class="camera-lens" cx="210" cy="221" r="67" />
    <g class="morph-eyes camera-eyes">
      <rect x="178" y="195" width="19" height="45" rx="9.5" />
      <rect x="224" y="191" width="19" height="45" rx="9.5" />
    </g>
    <rect class="camera-flash" x="302" y="148" width="40" height="24" rx="6" />
    <circle class="camera-record" cx="92" cy="158" r="9" />
    <g class="camera-focus">
      <path d="M137 162 V142 H157 M263 142 H283 V162 M137 278 V298 H157 M263 298 H283 V278" />
    </g>
  </g>
`;

const scenarios: readonly Scenario[] = [
  {
    id: "pen",
    number: "07",
    title: "Vibi es la pluma",
    state: "writing",
    result: "pen",
    description: "La silueta se afila y avanza sobre una linea de tinta; la cara vive dentro del cuerpo de la pluma.",
    visual: penVisual,
  },
  {
    id: "note",
    number: "08",
    title: "Vibi es la nota",
    state: "noting",
    result: "note",
    description: "Vibi se aplana en una hoja con esquina doblada y va llenando sus propias lineas.",
    visual: noteVisual,
  },
  {
    id: "camera",
    number: "09",
    title: "Vibi es la camara",
    state: "peeking",
    result: "camera",
    description: "El cuerpo se convierte en una camara y los ojos miran desde el objetivo antes de capturar.",
    visual: cameraVisual,
  },
] as const;

const root = document.querySelector<HTMLElement>("#morph-mock-root");
if (!root) throw new Error("Falta el contenedor del lote 03");

root.innerHTML = `
  <header class="morph-heading">
    <div>
      <p>Transformaciones completas / lote 03</p>
      <h1>Escribir, anotar y mirar.<br />Vibi toma otra forma.</h1>
    </div>
    <div class="morph-controls">
      <span><i></i> Ciclo de 6 segundos</span>
      <button type="button" id="morph-replay-all">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></svg>
        Repetir lote 03
      </button>
    </div>
  </header>
  <section class="morph-grid" aria-label="Tercer lote de transformaciones"></section>
  <footer class="morph-note">
    <span>07 writing / 08 noting / 09 peeking</span>
    <p>Lote aprobado y aplicado al companion.</p>
  </footer>
`;

const grid = root.querySelector<HTMLElement>(".morph-grid");
if (!grid) throw new Error("Falta la cuadricula del lote 03");
const staticPreview = new URLSearchParams(window.location.search).has("preview");

const mounted = scenarios.map((scenario) => {
  const card = document.createElement("article");
  card.className = `morph-card morph-card-${scenario.id}`;
  card.innerHTML = `
    <div class="morph-card-meta">
      <span>${scenario.number}</span>
      <code>VIBI → ${scenario.result}</code>
    </div>
    <div class="morph-stage">
      <div class="morph-stage-grid" aria-hidden="true"></div>
      <div class="morph-stage-glow" aria-hidden="true"></div>
      <div class="morph-face face-canvas face-canvas-companion" aria-label="${scenario.title}"></div>
      <div class="morph-status"><i></i><span>${scenario.title}</span></div>
    </div>
    <div class="morph-card-copy">
      <h2>${scenario.title}</h2>
      <p>${scenario.description}</p>
      <div class="morph-timeline" aria-hidden="true">
        <span>Vibi</span><span>Se desmonta</span><span>Es el objeto</span><span>Vuelve</span>
        <i></i>
      </div>
      <button type="button" class="morph-replay-one" aria-label="Repetir ${scenario.title}">
        Repetir <span>↻</span>
      </button>
    </div>
  `;
  grid.appendChild(card);

  const face = card.querySelector<HTMLElement>(".morph-face");
  if (!face) throw new Error(`Falta la cara de ${scenario.id}`);
  const scene = createCompanionScene(face, { frozen: true });
  const figure = face.querySelector<SVGGElement>(".companion-vibi-figure");
  if (!figure) throw new Error(`Falta la figura de ${scenario.id}`);
  figure.insertAdjacentHTML("afterbegin", scenario.visual);

  if (staticPreview) {
    scene.setState(scenario.state);
    card.classList.add("is-preview-03");
    return { play() {} };
  }

  let actionTimer = 0;
  let restTimer = 0;
  const play = () => {
    window.clearTimeout(actionTimer);
    window.clearTimeout(restTimer);
    scene.setState("idle");
    card.classList.remove("is-running");
    void card.offsetWidth;
    card.classList.add("is-running");
    actionTimer = window.setTimeout(() => scene.setState(scenario.state), 680);
    restTimer = window.setTimeout(() => scene.setState("idle"), 5_250);
  };

  card.querySelector<HTMLButtonElement>(".morph-replay-one")?.addEventListener("click", play);
  return { play };
});

const replayAll = () => mounted.forEach(({ play }) => play());
root.querySelector<HTMLButtonElement>("#morph-replay-all")?.addEventListener("click", replayAll);
replayAll();
window.setInterval(replayAll, 7_200);
