import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";

import { createCompanionScene } from "./lib/face/companion/scene";
import type { FaceState } from "./lib/face/estados";
import "./styles/companion.css";
import "./styles/companion-morphs.css";
import "./styles/companion-morph-mock.css";
import "./styles/companion-morph-mock-05.css";

interface Scenario {
  id: "dish" | "speaker" | "anvil";
  number: string;
  title: string;
  state: FaceState;
  result: string;
  description: string;
  visual: string;
}

const dishVisual = `
  <g class="morph-object morph-dish">
    <path class="dish-shadow" d="M71 82 C95 209 172 275 293 292 C305 190 238 102 71 82 Z" />
    <path class="dish-shell" d="M71 82 C95 209 172 275 293 292 C305 190 238 102 71 82 Z" />
    <path class="dish-face" d="M101 117 C131 208 190 250 263 263 C263 191 207 133 101 117 Z" />
    <g class="morph-eyes dish-eyes">
      <rect x="158" y="170" width="19" height="44" rx="9.5" transform="rotate(-28 168 192)" />
      <rect x="207" y="185" width="19" height="44" rx="9.5" transform="rotate(-28 217 207)" />
    </g>
    <path class="dish-arm" d="M247 258 L322 179" />
    <circle class="dish-node" cx="329" cy="171" r="17" />
    <path class="dish-stand" d="M192 273 L164 333 M242 283 L271 333 M146 333 H288" />
    <g class="dish-signal">
      <path d="M335 137 C359 143 374 158 382 180 M344 104 C388 113 411 141 416 177 M330 162 C339 164 345 170 349 180" />
    </g>
  </g>
`;

const speakerVisual = `
  <g class="morph-object morph-speaker">
    <rect class="speaker-shadow" x="80" y="42" width="260" height="304" rx="42" />
    <rect class="speaker-shell" x="80" y="42" width="260" height="304" rx="42" />
    <rect class="speaker-display" x="112" y="77" width="196" height="78" rx="24" />
    <g class="morph-eyes speaker-eyes">
      <rect x="156" y="92" width="18" height="42" rx="9" />
      <path d="M195 107 C208 122 225 122 238 107 L230 96 C221 107 212 107 203 96 Z" />
    </g>
    <circle class="speaker-ring" cx="210" cy="247" r="73" />
    <circle class="speaker-cone" cx="210" cy="247" r="49" />
    <circle class="speaker-core" cx="210" cy="247" r="17" />
    <g class="speaker-waves">
      <path d="M67 194 C35 220 35 273 67 299 M353 194 C385 220 385 273 353 299 M47 168 C-1 208 -1 286 47 326 M373 168 C421 208 421 286 373 326" />
    </g>
  </g>
`;

const anvilVisual = `
  <g class="morph-object morph-anvil">
    <path class="anvil-shadow" d="M46 114 H342 L383 146 L337 181 H273 V236 L312 315 H108 L147 236 V181 H78 Q48 181 36 151 Z" />
    <path class="anvil-shell" d="M46 114 H342 L383 146 L337 181 H273 V236 L312 315 H108 L147 236 V181 H78 Q48 181 36 151 Z" />
    <path class="anvil-face" d="M135 181 H285 V239 Q285 272 252 272 H168 Q135 272 135 239 Z" />
    <g class="morph-eyes anvil-eyes">
      <rect x="169" y="204" width="18" height="42" rx="9" />
      <rect x="222" y="200" width="18" height="42" rx="9" />
    </g>
    <g class="anvil-hammer">
      <rect x="274" y="48" width="98" height="45" rx="12" transform="rotate(-18 323 70)" />
      <path d="M296 86 L250 163" />
    </g>
    <g class="anvil-sparks">
      <path d="M275 126 L292 107 M291 139 H319 M261 114 V89 M249 129 L230 107" />
    </g>
    <path class="anvil-glow" d="M133 173 H287" />
  </g>
`;

const scenarios: readonly Scenario[] = [
  {
    id: "dish",
    number: "13",
    title: "Vibi es el enlace",
    state: "reaching",
    result: "network",
    description: "La figura se abre en una antena y orienta la mirada hacia el otro equipo hasta encontrarlo.",
    visual: dishVisual,
  },
  {
    id: "speaker",
    number: "14",
    title: "Vibi es el altavoz",
    state: "vibing",
    result: "speaker",
    description: "El cuerpo se convierte en un altavoz; la cara marca el ritmo y el pulso sale por el cono.",
    visual: speakerVisual,
  },
  {
    id: "anvil",
    number: "15",
    title: "Vibi es la forja",
    state: "forjando",
    result: "forge",
    description: "Vibi se vuelve yunque, recibe cada golpe y deja ver las chispas mientras nace la herramienta.",
    visual: anvilVisual,
  },
] as const;

const root = document.querySelector<HTMLElement>("#morph-mock-root");
if (!root) throw new Error("Falta el contenedor del lote 05");

root.innerHTML = `
  <header class="morph-heading">
    <div>
      <p>Transformaciones completas / lote 05</p>
      <h1>Conectar, sonar y forjar.<br />Vibi amplía su alcance.</h1>
    </div>
    <div class="morph-controls">
      <span><i></i> Ciclo de 6 segundos</span>
      <button type="button" id="morph-replay-all"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></svg>Repetir lote 05</button>
    </div>
  </header>
  <section class="morph-grid" aria-label="Quinto lote de transformaciones"></section>
  <footer class="morph-note"><span>13 reaching / 14 vibing / 15 forjando</span><p>Lote aprobado y aplicado al companion.</p></footer>
`;

const grid = root.querySelector<HTMLElement>(".morph-grid");
if (!grid) throw new Error("Falta la cuadricula del lote 05");
const staticPreview = new URLSearchParams(window.location.search).has("preview");

const mounted = scenarios.map((scenario) => {
  const card = document.createElement("article");
  card.className = `morph-card morph-card-${scenario.id}`;
  card.innerHTML = `
    <div class="morph-card-meta"><span>${scenario.number}</span><code>VIBI → ${scenario.result}</code></div>
    <div class="morph-stage"><div class="morph-stage-grid" aria-hidden="true"></div><div class="morph-stage-glow" aria-hidden="true"></div><div class="morph-face face-canvas face-canvas-companion" aria-label="${scenario.title}"></div><div class="morph-status"><i></i><span>${scenario.title}</span></div></div>
    <div class="morph-card-copy"><h2>${scenario.title}</h2><p>${scenario.description}</p><div class="morph-timeline" aria-hidden="true"><span>Vibi</span><span>Se desmonta</span><span>Es el objeto</span><span>Vuelve</span><i></i></div><button type="button" class="morph-replay-one" aria-label="Repetir ${scenario.title}">Repetir <span>↻</span></button></div>
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
    card.classList.add("is-preview-05");
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
