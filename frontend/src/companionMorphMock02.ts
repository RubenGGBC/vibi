import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";

import { createCompanionScene } from "./lib/face/companion/scene";
import type { FaceState } from "./lib/face/estados";
import "./styles/companion.css";
import "./styles/companion-morphs.css";
import "./styles/companion-morph-mock.css";
import "./styles/companion-morph-mock-02.css";

interface Scenario {
  id: "browser" | "folder" | "book";
  number: string;
  title: string;
  state: FaceState;
  result: string;
  description: string;
  visual: string;
}

const browserVisual = `
  <g class="morph-object morph-browser">
    <rect class="browser-shell-shadow" x="47" y="82" width="326" height="235" rx="25" />
    <rect class="browser-shell" x="47" y="82" width="326" height="235" rx="25" />
    <path class="browser-divider" d="M48 127 H372" />
    <circle class="browser-dot browser-dot-red" cx="75" cy="104" r="6" />
    <circle class="browser-dot" cx="95" cy="104" r="6" />
    <circle class="browser-dot" cx="115" cy="104" r="6" />
    <rect class="browser-address" x="138" y="94" width="205" height="21" rx="10.5" />
    <g class="morph-eyes browser-eyes">
      <rect x="131" y="164" width="21" height="48" rx="10.5" />
      <rect x="183" y="160" width="21" height="48" rx="10.5" />
    </g>
    <g class="browser-results">
      <rect x="242" y="157" width="82" height="12" rx="6" />
      <rect x="242" y="181" width="62" height="8" rx="4" />
      <rect x="242" y="205" width="91" height="8" rx="4" />
      <path class="browser-scan" d="M89 245 H333" />
      <rect x="89" y="264" width="104" height="9" rx="4.5" />
      <rect x="89" y="284" width="171" height="7" rx="3.5" />
    </g>
  </g>
`;

const folderVisual = `
  <g class="morph-object morph-folder">
    <path class="folder-shadow" d="M57 124 Q57 101 80 101 H158 L181 78 H258 Q278 78 281 101 H340 Q363 101 363 124 V298 Q363 318 341 318 H79 Q57 318 57 298 Z" />
    <path class="folder-back" d="M57 124 Q57 101 80 101 H158 L181 78 H258 Q278 78 281 101 H340 Q363 101 363 124 V298 H57 Z" />
    <path class="folder-front" d="M57 163 Q57 143 78 143 H342 Q363 143 363 163 V298 Q363 318 341 318 H79 Q57 318 57 298 Z" />
    <g class="morph-eyes folder-eyes">
      <rect x="157" y="204" width="21" height="49" rx="10.5" />
      <rect x="211" y="200" width="21" height="49" rx="10.5" />
    </g>
    <g class="folder-files">
      <path d="M105 155 V111 H179 L196 128 H305 V155" />
      <path d="M125 142 V99 H201 L216 115 H323 V151" />
    </g>
    <path class="folder-search-line" d="M111 281 H306" />
  </g>
`;

const bookVisual = `
  <g class="morph-object morph-book">
    <path class="book-cover" d="M42 111 Q119 83 205 126 Q291 83 378 111 V310 Q292 282 205 323 Q119 282 42 310 Z" />
    <path class="book-page book-page-left" d="M55 99 Q130 75 205 119 V302 Q130 263 55 292 Z" />
    <path class="book-page book-page-right" d="M205 119 Q280 75 365 99 V292 Q280 263 205 302 Z" />
    <path class="book-spine" d="M205 119 V302" />
    <g class="morph-eyes book-eyes">
      <rect x="132" y="166" width="20" height="47" rx="10" />
      <rect x="263" y="162" width="20" height="47" rx="10" />
    </g>
    <g class="book-lines">
      <path d="M86 238 H169 M91 258 H158 M247 236 H333 M255 257 H323" />
    </g>
    <path class="book-mark" d="M205 285 L220 331 L205 322 L190 331 Z" />
  </g>
`;

const scenarios: readonly Scenario[] = [
  {
    id: "browser",
    number: "04",
    title: "Vibi es el navegador",
    state: "browsing",
    result: "browser",
    description: "El ala se estira hasta ser la barra superior y la cara queda dentro de la pagina que esta recorriendo.",
    visual: browserVisual,
  },
  {
    id: "folder",
    number: "05",
    title: "Vibi es la carpeta",
    state: "rummaging",
    result: "folder",
    description: "La silueta se pliega como un archivador y sus ojos rebuscan entre documentos que asoman por arriba.",
    visual: folderVisual,
  },
  {
    id: "book",
    number: "06",
    title: "Vibi es el libro",
    state: "reading",
    result: "book",
    description: "La figura se abre en dos paginas; conserva un ojo en cada lado y la chistera marca la lectura.",
    visual: bookVisual,
  },
] as const;

const root = document.querySelector<HTMLElement>("#morph-mock-root");
if (!root) throw new Error("Falta el contenedor del lote 02");

root.innerHTML = `
  <header class="morph-heading">
    <div>
      <p>Transformaciones completas / lote 02</p>
      <h1>Navegar, rebuscar y leer.<br />Tres nuevas formas de Vibi.</h1>
    </div>
    <div class="morph-controls">
      <span><i></i> Ciclo de 6 segundos</span>
      <button type="button" id="morph-replay-all">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></svg>
        Repetir lote 02
      </button>
    </div>
  </header>
  <section class="morph-grid" aria-label="Segundo lote de transformaciones"></section>
  <footer class="morph-note">
    <span>04 browsing / 05 rummaging / 06 reading</span>
    <p>Lote aprobado y aplicado al companion.</p>
  </footer>
`;

const grid = root.querySelector<HTMLElement>(".morph-grid");
if (!grid) throw new Error("Falta la cuadricula del lote 02");
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
    card.classList.add("is-preview-02");
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
