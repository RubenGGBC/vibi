import { createContext, useContext, type MutableRefObject } from "react";
import type * as THREE from "three";

import type { MapaEjes } from "../../lib/estudio/ejes";
import type { Herramienta, Seleccion, Vista3D } from "../../lib/estudio/manipulacion";
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
  manipulacion: Manipulacion;
}

/** Transformación local de un nodo, sin lo que le pone la vista (explosión, giros). */
export interface Transformacion {
  posicion: number[];
  rotacion: number[];
  escala: number[];
}

/** Lo que el alumno hace con el ratón sobre los objetos (ver `manipulacion.ts`). */
export interface Manipulacion {
  seleccion: Seleccion | null;
  herramienta: Herramienta;
  vista: Vista3D;
  seleccionar: (seleccion: Seleccion | null) => void;
  /** El nodo de cada objeto (`id`) y de cada parte (`id.parte`), para el gizmo. */
  nodos: MutableRefObject<Map<string, THREE.Object3D>>;
  /** Cómo leer la transformación propia de cada parte, quitando la de la vista. */
  lectores: MutableRefObject<Map<string, () => Transformacion>>;
  /** La clave que se está arrastrando: ese nodo no lo recolocan sus fórmulas. */
  arrastrando: MutableRefObject<string | null>;
  /** Cuándo se soltó el gizmo: ese clic no deselecciona. */
  soltado: MutableRefObject<number>;
  /** Vacío sin corte; un plano con él. */
  planos: THREE.Plane[];
  /** Con algo aislado, los objetos que se pintan. */
  aislados: Set<string> | null;
  /** Articulaciones que el alumno fija con su deslizador (`claveArticulacion`). */
  articulaciones: Record<string, number>;
}

export const Contexto = createContext<ContextoEstudio | null>(null);

export function useEstudio(): ContextoEstudio {
  const valor = useContext(Contexto);
  if (!valor) throw new Error("Fuera de la escena de Estudio");
  return valor;
}

/** Lo que el ratón deja hacer sobre un objeto o una parte. */
export function useSeleccionado(id: string): { objeto: boolean; parte: string | null } {
  const { seleccion } = useEstudio().manipulacion;
  if (seleccion?.id !== id) return { objeto: false, parte: null };
  return { objeto: seleccion.parte === null, parte: seleccion.parte };
}

/** Atenuado: hay algo resaltado en este paso y no es este elemento. */
export function useAtenuado(id: string): { resaltado: boolean; atenuado: boolean } {
  const { paso } = useEstudio();
  const resaltado = paso.resaltados.has(id);
  return { resaltado, atenuado: paso.resaltados.size > 0 && !resaltado };
}
