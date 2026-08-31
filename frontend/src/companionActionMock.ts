import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";

import { createCompanionScene } from "./lib/face/companion/scene";
import type { FaceState } from "./lib/face/estados";
import "./styles/companion.css";
import "./styles/companion-action-mock.css";

interface Scenario {
  id: "web" | "terminal" | "tool";
  number: string;
  title: string;
  state: FaceState;
  stateLabel: string;
  description: string;
  hatVisual: string;
}

const searchHat = `
  <g class="hat-action hat-search">
    <g class="hat-search-card">
      <rect x="154" y="142" width="76" height="48" rx="7" />
      <path d="M168 156 H216 M168 166 H207 M168 176 H196" />
    </g>
    <g class="hat-search-lens">
      <circle cx="273" cy="179" r="14" />
      <path d="M283 189 L296 202" />
    </g>
    <circle class="hat-search-ping" cx="273" cy="179" r="20" />
  </g>
`;

const terminalHat = `
  <g class="hat-action hat-terminal">
    <rect class="hat-terminal-screen" x="137" y="105" width="96" height="61" rx="8" />
    <g class="hat-terminal-copy">
      <circle cx="149" cy="116" r="2.5" />
      <circle cx="158" cy="116" r="2.5" />
      <path d="M151 135 L160 142 L151 149 M169 149 H188" />
      <path class="hat-terminal-line" d="M198 149 H218" />
    </g>
  </g>
`;

const toolHat = `
  <g class="hat-action hat-tool">
    <path class="hat-tool-slot" d="M194 188 C211 177 231 168 250 163" />
    <g class="hat-tool-gear">
      <path d="M239 66 L246 62 L251 67 L258 66 L261 73 L267 77 L264 84 L266 91 L259 95 L255 102 L248 99 L241 102 L237 96 L229 94 L230 86 L226 80 L232 74 Z" />
      <circle cx="247" cy="82" r="7" />
    </g>
    <g class="hat-tool-bits">
      <rect x="215" y="118" width="10" height="10" rx="2" />
      <rect x="233" y="132" width="8" height="8" rx="2" />
      <rect x="249" y="113" width="6" height="6" rx="2" />
    </g>
  </g>
`;

const scenarios: readonly Scenario[] = [
  {
    id: "web",
    number: "01",
    title: "Buscar en internet",
    state: "searching",
    stateLabel: "searching",
    description: "El ala se levanta, sale una ficha y una lupa recorre la diagonal del sombrero.",
    hatVisual: searchHat,
  },
  {
    id: "terminal",
    number: "02",
    title: "Entrar al terminal",
    state: "hacking",
    stateLabel: "hacking",
    description: "La copa se comprime y se convierte en una pequeña pantalla; la cara conserva el prompt.",
    hatVisual: terminalHat,
  },
  {
    id: "tool",
    number: "03",
    title: "Usar herramienta",
    state: "working",
    stateLabel: "working",
    description: "La chistera se abre, procesa la herramienta como un mecanismo y vuelve a cerrarse.",
    hatVisual: toolHat,
  },
] as const;

const root = document.querySelector<HTMLElement>("#action-mock-root");
if (!root) throw new Error("Falta el contenedor del mock de acciones");

root.innerHTML = `
  <header class="action-mock-heading">
    <div>
      <p>Prueba de movimiento / companion local</p>
      <h1>Vibi hace visible lo que está haciendo.</h1>
    </div>
    <div class="action-mock-controls">
      <span><i></i> Secuencia de 6 segundos</span>
      <button type="button" id="replay-all">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></svg>
        Repetir las tres
      </button>
    </div>
  </header>
  <section class="action-mock-grid" aria-label="Tres propuestas de animación"></section>
  <footer class="action-mock-note">
    <span>El personaje y los estados son los reales.</span>
    <p>Los objetos y transiciones son el mock que se validará antes de llevarlo al companion.</p>
  </footer>
`;

const grid = root.querySelector<HTMLElement>(".action-mock-grid");
if (!grid) throw new Error("Falta la cuadrícula del mock");

const mounted = scenarios.map((scenario) => {
  const card = document.createElement("article");
  card.className = `action-card action-card-${scenario.id}`;
  card.innerHTML = `
    <div class="action-card-meta">
      <span>${scenario.number}</span>
      <code>${scenario.stateLabel}</code>
    </div>
    <div class="action-stage">
      <div class="stage-grid" aria-hidden="true"></div>
      <div class="stage-glow" aria-hidden="true"></div>
      <div class="mock-face face-canvas face-canvas-companion" aria-label="Vibi: ${scenario.title}"></div>
      <div class="action-status"><i></i><span>${scenario.title}</span></div>
    </div>
    <div class="action-card-copy">
      <h2>${scenario.title}</h2>
      <p>${scenario.description}</p>
      <div class="action-timeline" aria-hidden="true">
        <span>Reposo</span><span>Transición</span><span>Acción</span><span>Vuelve</span>
        <i></i>
      </div>
      <button type="button" class="replay-one" aria-label="Repetir ${scenario.title}">
        Repetir <span>↻</span>
      </button>
    </div>
  `;
  grid.appendChild(card);

  const face = card.querySelector<HTMLElement>(".mock-face");
  if (!face) throw new Error(`Falta la cara del escenario ${scenario.id}`);
  const scene = createCompanionScene(face, { morphs: false });
  const hat = face.querySelector<SVGGElement>(".companion-vibi-hat");
  if (!hat) throw new Error(`Falta la chistera del escenario ${scenario.id}`);
  hat.insertAdjacentHTML("beforeend", scenario.hatVisual);

  let actionTimer = 0;
  let restTimer = 0;
  const play = () => {
    window.clearTimeout(actionTimer);
    window.clearTimeout(restTimer);
    scene.setState("idle");
    card.classList.remove("is-running");
    void card.offsetWidth;
    card.classList.add("is-running");
    actionTimer = window.setTimeout(() => scene.setState(scenario.state), 620);
    restTimer = window.setTimeout(() => scene.setState("idle"), 5_250);
  };

  card.querySelector<HTMLButtonElement>(".replay-one")?.addEventListener("click", play);
  return { play };
});

const replayAll = () => mounted.forEach(({ play }) => play());
root.querySelector<HTMLButtonElement>("#replay-all")?.addEventListener("click", replayAll);
replayAll();
window.setInterval(replayAll, 7_200);
