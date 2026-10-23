import { createContext, useContext, type MutableRefObject } from "react";

import type { MapaEjes } from "../../lib/estudio/ejes";
import type { Parametro } from "../../lib/estudio/tipos";
import type { EstadoDePaso } from "../../lib/estudio/visibilidad";

/** Lo que necesita cualquier elemento para pintarse, sin pasarlo por props. */
export interface ContextoEstudio {
  valores: Record<string, number>;
  /** La definición de cada deslizador, por id (para saber sus límites). */
  parametros: Record<string, Parametro>;
  paso: EstadoDePaso;
  mapa: MapaEjes;
  /** Fotograma actual de cada reproductor (grafos y ordenaciones). */
  fotogramas: Record<string, number>;
  /** ¿Las simulaciones corren? */
  enMarcha: boolean;
  /** Se reinicia todo lo que tenga estado propio (simulaciones). */
  reinicio: number;
  /**
   * El estado que cambia en cada fotograma: el tiempo de la escena y las
   * variables de los sistemas dinámicos. Va en una ref y no en el estado de
   * React porque se lee 60 veces por segundo desde `useFrame`.
   */
  vivo: MutableRefObject<{ t: number; vars: Record<string, number> }>;
}

export const Contexto = createContext<ContextoEstudio | null>(null);

export function useEstudio(): ContextoEstudio {
  const valor = useContext(Contexto);
  if (!valor) throw new Error("Fuera de la escena de Estudio");
  return valor;
}

/** Atenuado: hay algo resaltado en este paso y no es este elemento. */
export function useAtenuado(id: string): { resaltado: boolean; atenuado: boolean } {
  const { paso } = useEstudio();
  const resaltado = paso.resaltados.has(id);
  return { resaltado, atenuado: paso.resaltados.size > 0 && !resaltado };
}
