import { useEffect, useRef } from "react";

import type { FaceScene, FaceState, Senales } from "../lib/face";
import { createFoxScene } from "../lib/face/companion/fox";
import "../styles/fox-agent.css";

/** The local pet receives the same mood and live signals as the voice agent. */
export function FoxVibi({ state, senales }: { state: FaceState; senales: Senales }) {
  const container = useRef<HTMLSpanElement>(null);
  const scene = useRef<FaceScene | null>(null);

  useEffect(() => {
    const host = container.current;
    if (!host) return;
    const mounted = createFoxScene(host);
    scene.current = mounted;
    const move = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      mounted.setPointer(((event.clientX - rect.left) / rect.width) * 2 - 1, ((event.clientY - rect.top) / rect.height) * 2 - 1);
    };
    const leave = () => mounted.clearPointer();
    window.addEventListener("pointermove", move);
    window.addEventListener("blur", leave);
    document.documentElement.addEventListener("pointerleave", leave);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("blur", leave);
      document.documentElement.removeEventListener("pointerleave", leave);
      mounted.dispose();
      scene.current = null;
    };
  }, []);

  useEffect(() => scene.current?.setState(state), [state]);
  useEffect(() => scene.current?.setSenales(senales), [senales]);

  return <span ref={container} className="face-canvas fox-agent-host" aria-hidden="true" />;
}
