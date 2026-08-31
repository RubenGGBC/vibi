import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";

import { createCompanionScene } from "./lib/face/companion/scene";
import "./styles/companion.css";
import "./styles/companion-morphs.css";
import "./styles/companion-morph-mock.css";
import "./styles/companion-morph-mock-final.css";

const podVisual = `
  <g class="morph-object morph-pod">
    <path class="pod-shadow" d="M210 35 C292 35 337 126 329 235 C323 321 275 346 210 346 C145 346 97 321 91 235 C83 126 128 35 210 35 Z" />
    <path class="pod-shell" d="M210 35 C292 35 337 126 329 235 C323 321 275 346 210 346 C145 346 97 321 91 235 C83 126 128 35 210 35 Z" />
    <path class="pod-hatch" d="M123 139 Q210 91 297 139 V270 Q210 315 123 270 Z" />
    <g class="morph-eyes pod-eyes">
      <rect x="169" y="163" width="19" height="45" rx="9.5" />
      <path d="M215 179 C229 196 248 196 262 179 L254 167 C243 180 233 180 223 167 Z" />
    </g>
    <path class="pod-desk" d="M143 235 H278 M160 235 V271 M261 235 V271" />
    <g class="pod-gear">
      <circle cx="210" cy="250" r="22" />
      <circle cx="210" cy="250" r="8" />
      <path d="M210 220 V229 M210 271 V280 M180 250 H189 M231 250 H240 M189 229 L195 235 M225 265 L231 271 M231 229 L225 235 M195 265 L189 271" />
    </g>
    <g class="pod-lights">
      <circle cx="151" cy="299" r="7" />
      <circle cx="175" cy="307" r="5" />
      <path d="M241 303 H278" />
    </g>
    <path class="pod-seam" d="M210 42 V104" />
  </g>
`;

const root = document.querySelector<HTMLElement>("#morph-mock-root");
if (!root) throw new Error("Falta el contenedor del mock final");

root.innerHTML = `
  <header class="morph-heading">
    <div>
      <p>Transformación completa / estado final</p>
      <h1>Vibi se recoge.<br />La trastienda sigue trabajando.</h1>
    </div>
    <div class="morph-controls">
      <span><i></i> Ciclo de 6 segundos</span>
      <button type="button" id="morph-replay-all"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></svg>Repetir transformación</button>
    </div>
  </header>
  <section class="morph-grid" aria-label="Transformación de trastienda">
    <article class="morph-card morph-card-pod">
      <div class="morph-card-meta"><span>16</span><code>VIBI → BACKSTAGE_POD</code></div>
      <div class="morph-stage"><div class="morph-stage-grid" aria-hidden="true"></div><div class="morph-stage-glow" aria-hidden="true"></div><div class="morph-face face-canvas face-canvas-companion" aria-label="Vibi es la trastienda"></div><div class="morph-status"><i></i><span>Trabajando en la trastienda</span></div></div>
      <div class="morph-card-copy"><h2>Vibi es la cápsula-taller</h2><p>Se recoge en un espacio pequeño, baja la intensidad y mantiene dentro un mecanismo que confirma que sigue trabajando.</p><div class="morph-timeline" aria-hidden="true"><span>Vibi</span><span>Se recoge</span><span>Trastienda</span><span>Vuelve</span><i></i></div><button type="button" class="morph-replay-one">Repetir <span>↻</span></button></div>
    </article>
  </section>
  <footer class="morph-note"><span>16 trastienda</span><p>Transformacion aprobada y aplicada al companion y a la app core local.</p></footer>
`;

const card = root.querySelector<HTMLElement>(".morph-card-pod");
const face = root.querySelector<HTMLElement>(".morph-face");
if (!card || !face) throw new Error("Falta la escena de trastienda");
const scene = createCompanionScene(face, { frozen: true });
const figure = face.querySelector<SVGGElement>(".companion-vibi-figure");
if (!figure) throw new Error("Falta la figura de trastienda");
figure.insertAdjacentHTML("afterbegin", podVisual);

const staticPreview = new URLSearchParams(window.location.search).has("preview");
let actionTimer = 0;
let restTimer = 0;
const play = () => {
  window.clearTimeout(actionTimer);
  window.clearTimeout(restTimer);
  scene.setState("idle");
  card.classList.remove("is-running");
  void card.offsetWidth;
  card.classList.add("is-running");
  actionTimer = window.setTimeout(() => scene.setState("trastienda"), 680);
  restTimer = window.setTimeout(() => scene.setState("idle"), 5_250);
};

if (staticPreview) {
  scene.setState("trastienda");
  card.classList.add("is-preview-final");
} else {
  root.querySelector<HTMLButtonElement>("#morph-replay-all")?.addEventListener("click", play);
  root.querySelector<HTMLButtonElement>(".morph-replay-one")?.addEventListener("click", play);
  play();
  window.setInterval(play, 7_200);
}
