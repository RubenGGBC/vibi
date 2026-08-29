import { COMPANION_GEOMETRY as G, COMPANION_VIEWBOX } from "./geometry";

const NS = "http://www.w3.org/2000/svg";

const create = <K extends keyof SVGElementTagNameMap>(
  tag: K,
  className?: string,
): SVGElementTagNameMap[K] => {
  const element = document.createElementNS(NS, tag);
  if (className) element.setAttribute("class", className);
  return element;
};

const path = (d: string, className?: string): SVGPathElement => {
  const element = create("path", className);
  element.setAttribute("d", d);
  return element;
};

const mark = (group: SVGGElement, name: string): SVGGElement => {
  group.setAttribute("data-vibi-part", name);
  return group;
};

const paintStroke = (element: SVGElement, color: string, width: number) => {
  element.setAttribute("fill", "none");
  element.setAttribute("stroke", color);
  element.setAttribute("stroke-width", String(width));
  element.setAttribute("stroke-linecap", "round");
  element.setAttribute("stroke-linejoin", "round");
};

export interface CompanionRig {
  svg: SVGSVGElement;
  figure: SVGGElement;
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

/** Monta una sola vez las piezas que la escena moverá por atributos. */
export function createCompanionRig(uid: string): CompanionRig {
  const svg = create("svg", "vibi-svg companion-vibi-svg");
  svg.setAttribute("viewBox", COMPANION_VIEWBOX);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.setAttribute("aria-hidden", "true");

  const defs = create("defs");
  const hatGradient = create("linearGradient");
  hatGradient.setAttribute("id", `${uid}-hat-gradient`);
  hatGradient.setAttribute("x1", "0");
  hatGradient.setAttribute("y1", "0");
  hatGradient.setAttribute("x2", "0.8");
  hatGradient.setAttribute("y2", "1");
  const hatBright = create("stop");
  hatBright.setAttribute("offset", "0");
  hatBright.setAttribute("stop-color", "var(--companion-vibi-red, #ff0b13)");
  const hatDeep = create("stop");
  hatDeep.setAttribute("offset", "1");
  hatDeep.setAttribute("stop-color", "var(--companion-vibi-deep-red, #c80713)");
  hatGradient.append(hatBright, hatDeep);

  const flameGradient = create("linearGradient");
  flameGradient.setAttribute("id", `${uid}-flame-gradient`);
  flameGradient.setAttribute("x1", "0");
  flameGradient.setAttribute("y1", "1");
  flameGradient.setAttribute("x2", "0.8");
  flameGradient.setAttribute("y2", "0");
  const flameDeep = create("stop");
  flameDeep.setAttribute("offset", "0");
  flameDeep.setAttribute("stop-color", "var(--companion-vibi-deep-red, #c80713)");
  const flameBright = create("stop");
  flameBright.setAttribute("offset", "1");
  flameBright.setAttribute("stop-color", "var(--companion-vibi-red, #ff0b13)");
  flameGradient.append(flameDeep, flameBright);
  defs.append(hatGradient, flameGradient);
  svg.appendChild(defs);

  const figure = create("g", "companion-vibi-figure");
  const body = create("g", "companion-vibi-body");

  const face = mark(create("g", "companion-vibi-face"), "face");
  const faceShape = path(G.head);
  faceShape.setAttribute("fill", "var(--companion-vibi-white, #fff)");
  const mask = path(G.mask, "companion-vibi-mask");
  mask.setAttribute("fill", "var(--companion-vibi-black, #090310)");
  face.append(faceShape, mask);

  const jaw = mark(create("g", "companion-vibi-jaw"), "jaw");
  const jawShape = path(G.jaw);
  jawShape.setAttribute("fill", "var(--companion-vibi-white, #fff)");
  jaw.appendChild(jawShape);

  const flame = mark(create("g", "companion-vibi-flame"), "flame");
  const flameTongues = G.flameTongues.map((shape) => {
    const tongue = create("g", "companion-vibi-flame-tongue");
    const outer = path(shape.outer, "companion-vibi-flame-outer");
    outer.setAttribute("fill", "var(--companion-vibi-white, #fff)");
    outer.setAttribute("stroke", "var(--companion-vibi-black, #090310)");
    outer.setAttribute("stroke-width", "4");
    outer.setAttribute("stroke-linejoin", "round");
    const inner = path(shape.inner, "companion-vibi-flame-inner");
    inner.setAttribute("fill", `url(#${uid}-flame-gradient)`);
    tongue.append(outer, inner);
    flame.appendChild(tongue);
    return tongue;
  });

  const hat = mark(create("g", "companion-vibi-hat"), "hat");
  const crown = path(G.crown, "companion-vibi-crown");
  crown.setAttribute("fill", `url(#${uid}-hat-gradient)`);
  for (const foldPath of [G.crownFoldA, G.crownFoldB]) {
    const fold = path(foldPath, "companion-vibi-fold");
    paintStroke(fold, "var(--companion-vibi-deep-red, #a20712)", 6);
    hat.appendChild(fold);
  }
  const brim = path(G.brim, "companion-vibi-brim");
  brim.setAttribute("fill", `url(#${uid}-hat-gradient)`);
  hat.prepend(crown);
  hat.appendChild(brim);

  const eyes = mark(create("g", "companion-vibi-eyes"), "eyes");
  const leftEye = path("M-9 -17 C-3 -22 7 -19 10 -11 L11 10 C8 20 -3 23 -9 16 C-12 8 -13 -8 -9 -17 Z");
  const rightEye = path("M-9 -17 C-3 -22 7 -19 10 -11 L11 10 C8 20 -3 23 -9 16 C-12 8 -13 -8 -9 -17 Z");
  leftEye.setAttribute("transform", `translate(${G.eyeAnchors[0].x} ${G.eyeAnchors[0].y})`);
  rightEye.setAttribute("transform", `translate(${G.eyeAnchors[1].x} ${G.eyeAnchors[1].y})`);
  for (const eye of [leftEye, rightEye]) {
    eye.setAttribute("fill", "var(--companion-vibi-white, #fff)");
    eye.setAttribute("class", "companion-vibi-eye");
  }
  const mouth = path(G.mouth, "companion-vibi-mouth");
  paintStroke(mouth, "var(--companion-vibi-white, #fff)", 7);
  mouth.setAttribute("opacity", "0");
  eyes.append(leftEye, rightEye, mouth);

  const accessories = mark(create("g", "companion-vibi-accessories"), "accessories");
  const question = create("g", "companion-vibi-question");
  const questionShape = path(G.question);
  paintStroke(questionShape, "var(--companion-vibi-red, #ff0b13)", 10);
  question.setAttribute("opacity", "0");
  question.appendChild(questionShape);

  const wave = create("g", "companion-vibi-wave");
  const waveBars = [22, 38, 55, 36, 23].map((height, index) => {
    const bar = create("rect");
    bar.setAttribute("x", String(285 + index * 17));
    bar.setAttribute("y", String(291 - height / 2));
    bar.setAttribute("width", "9");
    bar.setAttribute("height", String(height));
    bar.setAttribute("rx", "4.5");
    bar.setAttribute("fill", "var(--companion-vibi-red, #ff0b13)");
    wave.appendChild(bar);
    return bar;
  });
  wave.setAttribute("opacity", "0");

  const terminal = create("g", "companion-vibi-terminal");
  const terminalDash = path(G.terminalDash);
  const terminalChevron = path(G.terminalChevron);
  paintStroke(terminalDash, "var(--companion-vibi-white, #fff)", 10);
  paintStroke(terminalChevron, "var(--companion-vibi-white, #fff)", 10);
  terminal.setAttribute("opacity", "0");
  terminal.append(terminalDash, terminalChevron);

  const magnifier = create("g", "companion-vibi-magnifier");
  const ring = create("circle");
  ring.setAttribute("cx", String(G.magnifierRing.cx));
  ring.setAttribute("cy", String(G.magnifierRing.cy));
  ring.setAttribute("r", String(G.magnifierRing.r));
  paintStroke(ring, "var(--companion-vibi-red, #ff0b13)", 9);
  const handle = path(G.magnifierHandle);
  paintStroke(handle, "var(--companion-vibi-red, #ff0b13)", 11);
  magnifier.setAttribute("opacity", "0");
  magnifier.append(ring, handle);

  accessories.append(question, wave, terminal, magnifier);
  body.append(face, jaw, flame, hat, eyes, accessories);
  figure.appendChild(body);
  svg.appendChild(figure);

  return {
    svg,
    figure,
    body,
    hat,
    leftEye,
    rightEye,
    mouth,
    flameTongues,
    question,
    waveBars,
    terminal,
    magnifier,
  };
}
