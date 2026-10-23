import type { Articulacion, Objeto } from "./tipos";

/**
 * Lo que el alumno hace con los objetos de la escena: elegir uno (o una parte
 * de un modelo), moverlo, girarlo o escalarlo con el gizmo, ocultarlo,
 * aislarlo, separar las piezas (vista explosionada) y cortar con un plano.
 *
 * Ocultar, aislar, explosionar y cortar son solo de esta ventana: miran la
 * escena de otra forma sin cambiarla. Mover, girar y escalar sí la cambian y
 * se guardan en el servidor.
 */

export type Herramienta = "elegir" | "mover" | "girar" | "escalar";

export interface Seleccion {
  id: string;
  /** Nombre de la parte del modelo, tal cual está en `partes`. */
  parte: string | null;
}

export type EjeDeCorte = "x" | "y" | "z";

export interface Corte {
  eje: EjeDeCorte;
  /** De 0 (todo cortado) a 1 (nada cortado), sobre la caja de los objetos. */
  posicion: number;
  invertir: boolean;
}

export interface Vista3D {
  /** 0: el modelo montado; 1: piezas separadas del todo. */
  explosion: number;
  corte: Corte | null;
  /** Ids de objeto u `id.parte` que no se pintan. */
  ocultos: Set<string>;
  /** Solo se pinta este objeto (y lo que cuelga de él). */
  aislado: string | null;
}

export const VISTA_INICIAL: Vista3D = { explosion: 0, corte: null, ocultos: new Set(), aislado: null };

const NUMERO = /^\s*[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?\s*$/i;

/** ¿Es un número fijo? Una fórmula con t o deslizadores no se toca a mano. */
export function esConstante(fuente: string): boolean {
  return NUMERO.test(fuente);
}

/** Un objeto entero se coloca a mano solo si nada lo anima. */
export function colocableAMano(objeto: Objeto): boolean {
  return [...objeto.posicion, ...objeto.rotacion, ...objeto.escala].every(esConstante);
}

export function clave(seleccion: Seleccion): string {
  return seleccion.parte ? `${seleccion.id}.${seleccion.parte}` : seleccion.id;
}

/** El objeto y todo lo que cuelga de él, por `padre`. */
export function rama(id: string, objetos: Objeto[]): Set<string> {
  const dentro = new Set([id]);
  let crece = true;
  while (crece) {
    crece = false;
    for (const o of objetos) {
      if (o.padre && dentro.has(o.padre) && !dentro.has(o.id)) {
        dentro.add(o.id);
        crece = true;
      }
    }
  }
  return dentro;
}

/** Grados a una cifra razonable: el gizmo da 89.99999 donde se quería 90. */
export function redondear(valor: number, decimales = 3): number {
  const f = 10 ** decimales;
  const r = Math.round(valor * f) / f;
  return Object.is(r, -0) ? 0 : r;
}

/** Las articulaciones de un objeto, con las de escenas antiguas (`giros`) como giros sin topes. */
export function articulacionesDe(objeto: Objeto): Articulacion[] {
  return [
    ...(objeto.giros ?? []).map((g): Articulacion => ({ partes: g.partes, tipo: "giro", eje: g.eje, valor: g.angulo })),
    ...(objeto.articulaciones ?? []),
  ];
}

/** Clave de la articulación `indice` de un objeto, para lo que el alumno fija a mano. */
export function claveArticulacion(id: string, indice: number): string {
  return `${id}#${indice}`;
}

/** El valor dentro de sus topes. */
export function enTopes(valor: number, articulacion: Articulacion): number {
  const minimo = articulacion.minimo ?? -Infinity;
  const maximo = articulacion.maximo ?? Infinity;
  return Math.min(Math.max(valor, minimo), maximo);
}

/** El recorrido del deslizador: los topes, o uno razonable si no los hay. */
export function recorrido(articulacion: Articulacion): [number, number] {
  const defecto: [number, number] = articulacion.tipo === "giro" ? [-180, 180] : [-1, 1];
  return [articulacion.minimo ?? defecto[0], articulacion.maximo ?? defecto[1]];
}
