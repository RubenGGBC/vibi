import { useEffect, useRef, useState } from "react";
import { loadFoxSprites, FOX_HEIGHT, FOX_WIDTH, type FoxSprites, type FoxAction } from "../lib/foxSprites";

export function Fox({ action = "idle", size = "large" }: { action?: FoxAction | "idle"; size?: "large" | "small" }) {
  const [sprites, setSprites] = useState<FoxSprites>();
  const [failed, setFailed] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let active = true;
    loadFoxSprites().then((value) => { if (active) setSprites(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!sprites) return;
    let frame = 0;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const draw = () => {
      const context = canvas.current?.getContext("2d");
      if (!context || document.hidden) return;
      context.clearRect(0, 0, FOX_WIDTH, FOX_HEIGHT);
      context.imageSmoothingEnabled = false;
      const image = action === "idle" ? sprites.animations[0][frame] : sprites.actions[action][frame];
      context.drawImage(image, 0, 0);
      frame = (frame + 1) % 8;
    };
    draw();
    if (reduced) return;
    const timer = window.setInterval(draw, action === "idle" ? 350 : 240);
    return () => window.clearInterval(timer);
  }, [sprites, action]);

  return <div className={`ud-fox ud-fox--${size}`}>
    <canvas ref={canvas} width={FOX_WIDTH} height={FOX_HEIGHT} role="img" aria-label={`Vibi, el zorro con sombrero rojo${action === "idle" ? "" : `: ${action}`}`} />
    {(!sprites || failed) && <span className="ud-fox-loading">{failed ? "No se pudo cargar la mascota" : "Preparando a Vibi…"}</span>}
  </div>;
}
