import { useEffect, useRef } from "react";

import { createFaceScene, type FaceScene, type FaceState } from "../lib/face3d";

/**
 * Monta la cara 3D dentro de su contenedor y le va pasando el estado.
 * Toda la maquinaria de Three.js vive en `lib/face3d`; aquí solo queda el
 * ciclo de vida de React.
 */
export function MorganaFace({ state }: { state: FaceState }) {
  const containerRef = useRef<HTMLSpanElement | null>(null);
  const sceneRef = useRef<FaceScene | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = createFaceScene(container);
    sceneRef.current = scene;
    if (!scene) return;

    const observer = new ResizeObserver(() => scene.resize());
    observer.observe(container);

    return () => {
      observer.disconnect();
      scene.dispose();
      sceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    sceneRef.current?.setState(state);
  }, [state]);

  return <span className="face-canvas" ref={containerRef} aria-hidden="true" />;
}
