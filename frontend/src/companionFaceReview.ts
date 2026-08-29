import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";

import referenceUrl from "../../docs/superpowers/assets/2026-08-29-vibi-eight-faces-reference.png";
import { createCompanionScene } from "./lib/face/companion/scene";
import type { FaceState } from "./lib/face/estados";
import "./styles/companion.css";
import "./styles/companion-face-review.css";

const CELLS = [
  ["Reposo", "idle"],
  ["Recelo", "recelo"],
  ["Contenta", "pleased"],
  ["Trabajando", "working"],
  ["Duda", "thinking"],
  ["Hablando", "speaking"],
  ["Ejecutando", "hacking"],
  ["Buscando", "searching"],
] as const satisfies ReadonlyArray<readonly [string, FaceState]>;

const root = document.querySelector<HTMLElement>("#review-root");
if (!root) throw new Error("Falta el contenedor de revisión de Vibi");

const heading = document.createElement("header");
heading.className = "review-heading";
heading.innerHTML = `
  <p>Comparación vectorial · companion local</p>
  <h1>Vibi — ocho caras</h1>
  <span>Referencia original arriba · SVG ejecutable abajo · vista congelada</span>
`;

const reference = document.createElement("section");
reference.className = "review-reference";
reference.setAttribute("aria-labelledby", "reference-title");
reference.innerHTML = `
  <div class="review-section-title">
    <h2 id="reference-title">01 / Referencia aprobada</h2>
    <span>PNG original · 1672 × 940</span>
  </div>
`;
const referenceImage = document.createElement("img");
referenceImage.src = referenceUrl;
referenceImage.alt = "Lámina original con las ocho caras de Vibi";
reference.appendChild(referenceImage);

const implementation = document.createElement("section");
implementation.className = "review-implementation";
implementation.setAttribute("aria-labelledby", "implementation-title");
implementation.innerHTML = `
  <div class="review-section-title">
    <h2 id="implementation-title">02 / Implementación SVG</h2>
    <span>Un único rig · ocho estados · 420 × 360 por celda</span>
  </div>
`;

const grid = document.createElement("div");
grid.className = "review-grid";

for (const [label, state] of CELLS) {
  const figure = document.createElement("figure");
  figure.className = "review-cell";
  figure.dataset.state = state;

  const stage = document.createElement("div");
  stage.className = "review-stage face-canvas-companion";
  stage.setAttribute("aria-label", `Vibi: ${label}`);

  const caption = document.createElement("figcaption");
  caption.innerHTML = `<strong>${label}</strong><span>${state}</span>`;

  figure.append(stage, caption);
  grid.appendChild(figure);

  const scene = createCompanionScene(stage, { frozen: true });
  scene.setState(state);
  scene.dibujar(1 / 60);
}

implementation.appendChild(grid);
root.append(heading, reference, implementation);
