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

export interface Sistema extends Base {
  tipo: "sistema";
  orden: string[];
  iniciales: Record<string, string>;
  ecuaciones: Record<string, string>;
  grafica: boolean;
}

export type Forma =
  | "esfera"
  | "caja"
  | "cilindro"
  | "cono"
  | "toro"
  | "plano"
  | "tubo"
  | "flecha"
  | "texto"
  | "grupo"
  | "modelo";

/** Partes de un modelo que giran (bisagra, eje) o se deslizan (cajón), con topes. */
export interface Articulacion {
  partes: string[];
  tipo: "giro" | "desliza";
  eje: "x" | "y" | "z";
  /** Grados (giro) o unidades de la escena (desliza), como fórmula. */
  valor: string;
  minimo?: number;
  maximo?: number;
  etiqueta?: string;
}

/** Escenas de antes de las articulaciones: un giro sin topes. */
export interface GiroDeParte {
  partes: string[];
  eje: "x" | "y" | "z";
  /** Grados, como fórmula. */
  angulo: string;
}

/** Lo que se cambia de una parte de un modelo: el agente la colorea u oculta;
 *  el alumno la mueve, gira o escala con el ratón (unidades del archivo). */
export interface AjusteDeParte {
  color?: string;
  oculta?: boolean;
  posicion?: number[];
  rotacion?: number[];
  escala?: number[];
}

export interface Objeto extends Base {
  tipo: "objeto";
  forma: Forma;
  padre: string | null;
  posicion: string[];
  rotacion: string[];
  escala: string[];
  tamano: string[];
  puntos?: string[][];
  direccion?: string[];
  texto?: string;
  /** forma "modelo": id de la biblioteca, su archivo y sus partes. */
  modelo?: string;
  url?: string;
  partes?: Record<string, string>;
  giros?: GiroDeParte[];
  articulaciones?: Articulacion[];
  ajustes?: Record<string, AjusteDeParte>;
  /** El alumno lo ha colocado o retocado a mano. */
  manual?: boolean;
  opacidad: number;
  brillo: number;
  estela: number;
  anima: boolean;
}

export type Elemento =
  | Sistema
  | Objeto
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
  /** Una por fallo, de menos a más. */
  pistas?: string[];
}

export interface Paso {
  /** Lo que Vibi le cuenta al alumno. */
  texto: string;
  /** Lo que tiene que quedarse, en una línea. */
  idea?: string | null;
  /** Lo que el alumno hace en este paso. */
  tarea?: string | null;
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
  /** Espacio libre de los objetos compuestos: ancho, alto, fondo. */
  espacio?: [number, number, number];
  parametros: Parametro[];
  elementos: Elemento[];
  pasos: Paso[];
  paso_actual: number;
  /** Lo que ha hecho el alumno: hasta dónde ha llegado y qué ha respondido. */
  progreso?: Progreso;
  actualizada_en: number | null;
}

export interface Progreso {
  visto_hasta: number;
  /** Por número de paso (desde 1): las opciones elegidas, en orden. */
  respuestas: Record<string, number[]>;
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
