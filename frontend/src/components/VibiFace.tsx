import { useEffect, useRef } from "react";

import {
  createFaceScene,
  type FacePerfil,
  type FaceScene,
  type FaceState,
} from "../lib/face3d";

/**
 * Monta la cara 3D dentro de su contenedor y le va pasando el estado.
 * Toda la maquinaria de Three.js vive en `lib/face3d`; aquí solo queda el
 * ciclo de vida de React.
 */
export function VibiFace({
  state,
  perfil,
}: {
  state: FaceState;
  perfil?: FacePerfil;
}) {
  const containerRef = useRef<HTMLSpanElement | null>(null);
  const sceneRef = useRef<FaceScene | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = createFaceScene(container, { perfil });
    sceneRef.current = scene;
    if (!scene) return;

    const observer = new ResizeObserver(() => scene.resize());
    observer.observe(container);

    return () => {
      observer.disconnect();
      scene.dispose();
      sceneRef.current = null;
    };
  }, [perfil]);

  useEffect(() => {
    sceneRef.current?.setState(state);
  }, [state]);

  // En el companion la cara ocupa casi toda la ventana, así que el ratón que
  // pasa por encima es una señal clara de que le estás prestando atención. En
  // la PWA no se escucha nada: allí la cara comparte página con el resto y
  // seguir el cursor la volvería inquieta sin motivo.
  useEffect(() => {
    if (perfil !== "companion") return;
    const container = containerRef.current;
    if (!container) return;

    const mover = (event: PointerEvent) => {
      const rect = container.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      sceneRef.current?.setPointer(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        ((event.clientY - rect.top) / rect.height) * 2 - 1,
      );
    };
    const soltar = () => sceneRef.current?.clearPointer();

    window.addEventListener("pointermove", mover);
    // `pointerleave` no burbujea, así que hay que colgarlo de la raíz para
    // enterarse de que el cursor salió de la ventana.
    document.documentElement.addEventListener("pointerleave", soltar);
    window.addEventListener("blur", soltar);

    return () => {
      window.removeEventListener("pointermove", mover);
      document.documentElement.removeEventListener("pointerleave", soltar);
      window.removeEventListener("blur", soltar);
    };
  }, [perfil]);

  return <span className="face-canvas" ref={containerRef} aria-hidden="true" />;
}
