import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";

import { createCompanionScene } from "./lib/face/companion/scene";
import type { FaceState } from "./lib/face/estados";
import "./styles/companion.css";
import "./styles/companion-morphs.css";
import "./styles/companion-morph-mock.css";
import "./styles/companion-morph-mock-04.css";

interface Scenario {
  id: "mouse" | "rocket" | "envelope";
  number: string;
  title: string;
  state: FaceState;
  result: string;
  description: string;
  visual: string;
}

const mouseVisual = `
  <g class="morph-object morph-mouse">
    <path class="mouse-shadow" d="M210 42 C292 42 337 101 337 189 V236 C337 310 287 342 210 342 C133 342 83 310 83 236 V189 C83 101 128 42 210 42 Z" />
    <path class="mouse-shell" d="M210 42 C292 42 337 101 337 189 V236 C337 310 287 342 210 342 C133 342 83 310 83 236 V189 C83 101 128 42 210 42 Z" />
    <path class="mouse-divider" d="M210 48 V135 M89 164 H331" />
    <rect class="mouse-wheel" x="198" y="74" width="24" height="50" rx="12" />
    <path class="mouse-face" d="M111 174 H309 V271 Q309 311 269 311 H151 Q111 311 111 271 Z" />
    <g class="morph-eyes mouse-eyes">
      <rect x="163" y="210" width="20" height="47" rx="10" />
      <path d="M213 226 C227 243 246 243 260 226 L252 214 C241 227 231 227 221 214 Z" />
    </g>
    <g class="mouse-clicks">
      <path d="M352 119 L372 99 M362 138 H390 M337 105 V77" />
    </g>
  </g>
`;

const rocketVisual = `
  <g class="morph-object morph-rocket">
    <path class="rocket-shadow" d="M210 36 C276 75 298 145 287 236 L337 292 L278 304 L244 267 H176 L142 304 L83 292 L133 236 C122 145 144 75 210 36 Z" />
    <path class="rocket-shell" d="M210 36 C276 75 298 145 287 236 L337 292 L278 304 L244 267 H176 L142 304 L83 292 L133 236 C122 145 144 75 210 36 Z" />
    <path class="rocket-face" d="M147 132 Q210 100 273 132 V232 Q210 265 147 232 Z" />
    <g class="morph-eyes rocket-eyes">
      <rect x="174" y="161" width="20" height="47" rx="10" />
      <rect x="226" y="157" width="20" height="47" rx="10" />
    </g>
    <circle class="rocket-port" cx="210" cy="94" r="18" />
    <g class="rocket-flame">
      <path d="M176 275 C167 316 187 339 210 354 C233 339 253 316 244 275 Z" />
      <path d="M190 282 C190 310 200 325 210 334 C220 325 230 310 230 282 Z" />
    </g>
    <g class="rocket-speed"><path d="M76 180 H42 M82 208 H57 M344 180 H378" /></g>
  </g>
`;

const envelopeVisual = `
  <g class="morph-object morph-envelope">
    <rect class="envelope-shadow" x="45" y="91" width="330" height="230" rx="25" />
    <rect class="envelope-shell" x="45" y="91" width="330" height="230" rx="25" />
    <path class="envelope-flap" d="M56 108 L210 229 L364 108" />
    <path class="envelope-folds" d="M55 307 L165 205 M365 307 L255 205" />
    <path class="envelope-face" d="M111 215 Q210 265 309 215 V293 H111 Z" />
    <g class="morph-eyes envelope-eyes">
      <rect x="168" y="241" width="19" height="44" rx="9.5" />
      <rect x="220" y="237" width="19" height="44" rx="9.5" />
    </g>
    <g class="envelope-speed">
      <path d="M25 145 H-14 M31 177 H6 M394 251 H363 M406 278 H374" />
    </g>
    <circle class="envelope-seal" cx="210" cy="204" r="19" />
  </g>
`;

const scenarios: readonly Scenario[] = [
  {
    id: "mouse",
    number: "10",
    title: "Vibi es el raton",
    state: "handling",
    result: "mouse",
    description: "La figura se redondea en un raton; el clic, el scroll y la mirada ocurren en el mismo cuerpo.",
    visual: mouseVisual,
  },
  {
    id: "rocket",
    number: "11",
    title: "Vibi es el lanzamiento",
    state: "launching",
    result: "rocket",
    description: "Vibi se comprime en un cohete y despega cuando abre una aplicacion, una ruta o una direccion.",
    visual: rocketVisual,
  },
  {
    id: "envelope",
    number: "12",
    title: "Vibi es el envio",
    state: "sending",
    result: "envelope",
    description: "La silueta se pliega en un sobre con rostro y toma impulso mientras mueve el archivo.",
    visual: envelopeVisual,
  },
] as const;

const root = document.querySelector<HTMLElement>("#morph-mock-root");
if (!root) throw new Error("Falta el contenedor del lote 04");

root.innerHTML = `
  <header class="morph-heading">
    <div>
      <p>Transformaciones completas / lote 04</p>
      <h1>Controlar, abrir y enviar.<br />Vibi entra en movimiento.</h1>
    </div>
    <div class="morph-controls">
      <span><i></i> Ciclo de 6 segundos</span>
      <button type="button" id="morph-replay-all">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></svg>
        Repetir lote 04
      </button>
    </div>
  </header>
  <section class="morph-grid" aria-label="Cuarto lote de transformaciones"></section>
  <footer class="morph-note">
    <span>10 handling / 11 launching / 12 sending</span>
    <p>Lote aprobado y aplicado al companion.</p>
  </footer>
`;

const grid = root.querySelector<HTMLElement>(".morph-grid");
if (!grid) throw new Error("Falta la cuadricula del lote 04");
const staticPreview = new URLSearchParams(window.location.search).has("preview");

const mounted = scenarios.map((scenario) => {
  const card = document.createElement("article");
  card.className = `morph-card morph-card-${scenario.id}`;
  card.innerHTML = `
    <div class="morph-card-meta"><span>${scenario.number}</span><code>VIBI → ${scenario.result}</code></div>
    <div class="morph-stage">
      <div class="morph-stage-grid" aria-hidden="true"></div><div class="morph-stage-glow" aria-hidden="true"></div>
      <div class="morph-face face-canvas face-canvas-companion" aria-label="${scenario.title}"></div>
      <div class="morph-status"><i></i><span>${scenario.title}</span></div>
    </div>
    <div class="morph-card-copy">
      <h2>${scenario.title}</h2><p>${scenario.description}</p>
      <div class="morph-timeline" aria-hidden="true"><span>Vibi</span><span>Se desmonta</span><span>Es el objeto</span><span>Vuelve</span><i></i></div>
      <button type="button" class="morph-replay-one" aria-label="Repetir ${scenario.title}">Repetir <span>↻</span></button>
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
    card.classList.add("is-preview-04");
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
