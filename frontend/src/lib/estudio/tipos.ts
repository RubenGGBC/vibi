/**
 * La escena de Estudio tal como la manda el servidor (`app/estudio/escena.py`).
 *
 * El cliente no decide nada de lo que se ve: pinta estos datos. Lo único que
 * vive aquí son los valores de los deslizadores que mueve el alumno y el
 * fotograma de cada reproductor.
 */

export type Rango = [number, number];

export interface Procedencia {
  origen: "engine" | "pubchem" | "catalogo" | "modelo";
  detalle: string;
  url?: string;
}

export interface Parametro {
  id: string;
  etiqueta: string;
  minimo: number;
  maximo: number;
  paso: number;
  valor: number;
}

interface Base {
  id: string;
  etiqueta: string;
  color: string;
  usa: string[];
  procedencia: Procedencia;
}

export interface Funcion extends Base {
  tipo: "funcion";
  expresion: string;
  variable: "x" | "t";
  dominio: Rango | null;
}

export interface Sucesion extends Base {
  tipo: "sucesion";
  expresion: string;
  desde: number;
  hasta: number | string;
  estilo: "barras" | "puntos" | "linea";
  acumulada: boolean;
}

export interface Superficie extends Base {
  tipo: "superficie";
  expresion: string;
  resolucion: number;
}

export interface Marca extends Base {
  tipo: "punto" | "vector" | "etiqueta";
  posicion: string[];
  desde?: string[];
}

export interface Simulacion extends Base {
  tipo: "simulacion";
  modelo: "pendulo" | "muelle" | "proyectil" | "onda";
  parametros: Record<string, number | string>;
  unidades: Record<string, string>;
  ecuacion: string;
}

export interface NodoGrafo {
  id: string;
  etiqueta: string;
  posicion: [number, number, number];
}

export interface AristaGrafo {
  desde: string;
  hasta: string;
  peso: number;
}

export interface FotogramaGrafo {
  actual: string | null;
  visitados: string[];
  frontera: string[];
  arista: [string, string] | null;
  distancias?: Record<string, number | null>;
  camino?: string[];
  mensaje: string;
}

export interface Grafo extends Base {
  tipo: "grafo";
  nodos: NodoGrafo[];
  aristas: AristaGrafo[];
  dirigido: boolean;
  recorrido: {
    algoritmo: string;
    origen: string;
    destino: string | null;
    fotogramas: FotogramaGrafo[];
    resultado: Record<string, unknown>;
  } | null;
}

export interface FotogramaOrdenacion {
  valores: number[];
  comparando: number[];
  escribiendo: number[];
  pivote: number | null;
  ordenados: number[];
  mensaje: string;
}

export interface Ordenacion extends Base {
  tipo: "ordenacion";
  algoritmo: string;
  valores: number[];
  fotogramas: FotogramaOrdenacion[];
  resultado: { comparaciones: number; escrituras: number };
}

export interface Atomo {
  elemento: string;
  posicion: [number, number, number];
}

export interface Molecula extends Base {
  tipo: "molecula";
  nombre: string;
  atomos: Atomo[];
  enlaces: { a: number; b: number; orden: number }[];
}

export interface ModeloGltf extends Base {
  tipo: "modelo";
  modelo_id: string;
  url: string;
  partes: Record<string, string>;
  resaltadas: string[];
}

export type Elemento =
  | Funcion
  | Sucesion
  | Superficie
  | Marca
  | Simulacion
  | Grafo
  | Ordenacion
  | Molecula
  | ModeloGltf;

export interface Pregunta {
  enunciado: string;
  opciones: string[];
  correcta: number;
  explicacion: string;
}

export interface Paso {
  texto: string;
  mostrar: string[];
  ocultar: string[];
  resaltar: string[];
  pregunta: Pregunta | null;
}

export interface Escena {
  version: number;
  titulo: string;
  modo: "2d" | "3d";
  ejes: { visibles: boolean; x: Rango; y: Rango; z: Rango };
  parametros: Parametro[];
  elementos: Elemento[];
  pasos: Paso[];
  paso_actual: number;
  actualizada_en: number | null;
}

export type ValoresParametros = Record<string, number>;

/** Los que se pintan sobre los ejes; el resto ocupa su propio bloque. */
export const TIPOS_DE_EJES = new Set([
  "funcion",
  "sucesion",
  "superficie",
  "punto",
  "vector",
  "etiqueta",
]);
