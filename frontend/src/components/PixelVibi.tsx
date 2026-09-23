import { useEffect, useRef } from "react";

import { createCompanionScene } from "../lib/face/companion/scene";
import { familyOf } from "../lib/face/companion/states";
import type { FaceState } from "../lib/face/estados";

// Un píxel equivale a cuatro unidades del rig original (420 × 360). Así el
// sombrero, las llamas y hasta los ojos conservan exactamente su dibujo.
const WIDTH = 105;
const HEIGHT = 90;

const COLORS = [
  [255, 33, 43],  // rojo iluminado
  [221, 5, 23],   // rojo en sombra
  [255, 250, 247], // marfil
  [13, 7, 19],    // tinta
] as const;

/**
 * Reduce la cara original a una paleta de cuatro tintas. El borde se decide
 * por píxel, no por antialiasing: al ampliarlo se ve una cuadrícula auténtica.
 */
function pixelate(ctx: CanvasRenderingContext2D, blush: boolean) {
  const image = ctx.getImageData(0, 0, WIDTH, HEIGHT);
  const { data } = image;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 145) {
      data[i + 3] = 0;
      continue;
    }
    let nearest: (typeof COLORS)[number] = COLORS[0];
    let distance = Infinity;
    for (const color of COLORS) {
      const difference =
        (data[i] - color[0]) ** 2 +
        (data[i + 1] - color[1]) ** 2 +
        (data[i + 2] - color[2]) ** 2;
      if (difference < distance) {
        nearest = color;
        distance = difference;
      }
    }
    data[i] = nearest[0];
    data[i + 1] = nearest[1];
    data[i + 2] = nearest[2];
    data[i + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
  if (blush) {
    // Los toques rosados solo van sobre la tinta de las mejillas, nunca sobre
    // el blanco de la mandíbula ni el rojo del ala.
    ctx.fillStyle = "#f87886";
    for (const [x, y] of [[38, 73], [64, 69]]) {
      const pixel = ctx.getImageData(x, y, 1, 1).data;
      if (pixel[0] === 13 && pixel[1] === 7) ctx.fillRect(x, y, 2, 1);
    }
  }
}

export function PixelVibi({ state = "idle", animated = false }: {
  state?: FaceState;
  animated?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const target = canvas.current;
    const ctx = target?.getContext("2d", { willReadFrequently: true });
    if (!target || !ctx) return;

    // La misma escena aprobada que mueve a la mascota de escritorio. Solo se
    // congela para tomar una imagen limpia de la expresión solicitada.
    const host = document.createElement("div");
    const scene = createCompanionScene(host, { frozen: true, morphs: false });
    scene.setState(state);
    scene.dibujar(1 / 60);
    const svg = host.querySelector("svg");
    if (!svg) {
      scene.dispose();
      return;
    }

    // Un poco más grandes y redondos que en el rig vectorial: a esta escala
    // eran solo tres píxeles y se perdía la mirada amable del original.
    if (["reposo", "trabajando", "buscando", "contenta"].includes(familyOf(state))) {
      svg.querySelectorAll(".companion-vibi-eye").forEach((eye) => {
        eye.setAttribute("transform", `${eye.getAttribute("transform")} scale(1.13 1.1)`);
      });
    }

    // Las variables CSS del companion viven fuera del SVG. En un <img> creado
    // desde un blob no se heredan, así que ponemos aquí sus cuatro tintas.
    const markup = new XMLSerializer().serializeToString(svg)
      .replaceAll("var(--companion-vibi-red, #ff0b13)", "#ff0b13")
      .replaceAll("var(--companion-vibi-red-shadow, #e8000d)", "#e8000d")
      .replaceAll("var(--companion-vibi-black, #090310)", "#090310")
      .replaceAll("var(--companion-vibi-white, #fff)", "#fff");
    scene.dispose();

    const url = URL.createObjectURL(new Blob([markup], { type: "image/svg+xml" }));
    const image = new Image();
    let disposed = false;
    image.onload = () => {
      if (disposed) return;
      ctx.clearRect(0, 0, WIDTH, HEIGHT);
      ctx.drawImage(image, 0, 0, WIDTH, HEIGHT);
      pixelate(ctx, ["reposo", "contenta", "hablando"].includes(familyOf(state)));
      URL.revokeObjectURL(url);
    };
    image.onerror = () => URL.revokeObjectURL(url);
    image.src = url;

    return () => {
      disposed = true;
      image.onload = null;
      image.onerror = null;
      URL.revokeObjectURL(url);
    };
  }, [state]);

  return (
    <canvas
      ref={canvas}
      width={WIDTH}
      height={HEIGHT}
      className={`pixel-vibi${animated ? " pixel-vibi--animated" : ""}`}
      role="img"
      aria-label={`Vibi pixel art: ${state}`}
    />
  );
}
