import { useEffect, useRef } from "react";

import {
  SENALES_QUIETAS,
  crearEscenaCara,
  type FacePerfil,
  type FaceScene,
  type FaceState,
  type Senales,
} from "../lib/face";

/**
 * Monta la cara dentro de su contenedor y le va pasando lo que sabe.
 *
 * Toda la maquinaria vive en `lib/face`; aquí solo queda el ciclo de vida de
 * React. Nada de esto vuelve a renderizar por fotograma: la escena posee sus
 * nodos SVG y les escribe atributos por su cuenta.
 */
export function VibiFace({
  state,
  perfil,
  senales = SENALES_QUIETAS,
}: {
  state: FaceState;
  perfil?: FacePerfil;
  senales?: Senales;
}) {
  const containerRef = useRef<HTMLSpanElement | null>(null);
  const sceneRef = useRef<FaceScene | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = crearEscenaCara(container, { perfil });
    sceneRef.current = scene;

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

  useEffect(() => {
    sceneRef.current?.setSenales(senales);
  }, [senales]);

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
