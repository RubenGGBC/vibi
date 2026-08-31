import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";

import { createCompanionScene } from "./lib/face/companion/scene";
import { MORPH_VISUALS, type CompanionMorph } from "./lib/face/companion/morphs";
import type { FaceState } from "./lib/face/estados";
import "./styles/companion.css";
import "./styles/companion-morphs.css";
import "./styles/companion-morph-mock.css";

interface MorphScenario {
  id: "search" | "terminal" | "tool";
  number: string;
  title: string;
  state: FaceState;
  result: string;
  description: string;
  morph: CompanionMorph;
}

const scenarios: readonly MorphScenario[] = [
  {
    id: "search",
    number: "01",
    title: "Vibi es la lupa",
    state: "searching",
    result: "magnifier",
    description: "La silueta se cierra sobre un cristal oscuro; ojos, rojo y chistera mantienen su identidad.",
    morph: "magnifier",
  },
  {
    id: "terminal",
    number: "02",
    title: "Vibi es el terminal",
    state: "hacking",
    result: "terminal",
    description: "El cuerpo se ensancha hasta ser la consola. Sus ojos son el prompt y la chistera firma la esquina.",
    morph: "terminal",
  },
  {
    id: "tool",
    number: "03",
    title: "Vibi es la herramienta",
    state: "working",
    result: "tool_engine",
    description: "La figura se recoge en un mecanismo universal, con la cara viva en el núcleo de la herramienta.",
    morph: "tool",
  },
] as const;

const root = document.querySelector<HTMLElement>("#morph-mock-root");
if (!root) throw new Error("Falta el contenedor del mock de transformaciones");

root.innerHTML = `
  <header class="morph-heading">
    <div>
      <p>Prueba independiente / transformación completa</p>
      <h1>Vibi no usa la herramienta.<br />Vibi se convierte en ella.</h1>
    </div>
    <div class="morph-controls">
      <span><i></i> Ciclo de 6 segundos</span>
      <button type="button" id="morph-replay-all">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></svg>
        Repetir transformaciones
      </button>
    </div>
  </header>
  <section class="morph-grid" aria-label="Tres transformaciones completas"></section>
  <footer class="morph-note">
    <span>La prueba de la chistera anterior queda guardada aparte.</span>
    <p>Este montaje explora un lenguaje distinto: Vibi pasa a ser el objeto.</p>
  </footer>
`;

const grid = root.querySelector<HTMLElement>(".morph-grid");
if (!grid) throw new Error("Falta la cuadrícula de transformaciones");
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
  const scene = createCompanionScene(face, { morphs: false });
  const figure = face.querySelector<SVGGElement>(".companion-vibi-figure");
  if (!figure) throw new Error(`Falta la figura de ${scenario.id}`);
  figure.insertAdjacentHTML("afterbegin", MORPH_VISUALS[scenario.morph]);

  if (staticPreview) {
    scene.setState(scenario.state);
    card.classList.add("is-preview");
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
