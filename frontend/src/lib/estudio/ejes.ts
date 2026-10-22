import type { Escena, Rango } from "./tipos";

/**
 * De coordenadas de los ejes a coordenadas del mundo 3D.
 *
 * Los datos pueden ir de 0 a 200 en x y de 0 a 1 en y: se dibujan en una caja
 * de tamaño fijo, escalando cada eje por separado. En 2D la caja es un plano
 * (x horizontal, y vertical). En 3D z es la altura, como en los libros: el
 * dato (x, y, z) va al mundo (X, Z_altura, −Y_profundidad).
 */
export interface MapaEjes {
  modo: "2d" | "3d";
  ancho: number;
  alto: number;
  fondo: number;
  ejes: Escena["ejes"];
  /** Punto de datos → mundo. En 2D `z` se ignora. */
  punto: (x: number, y: number, z?: number) => [number, number, number];
  /** Solo el valor vertical (y en 2D, z en 3D) → altura del mundo. */
  altura: (v: number) => number;
  /** ¿Está el valor vertical dentro de la caja (con un margen)? */
  dentro: (v: number) => boolean;
  /** Unidad de x en el mundo: el ancho de una barra de una sucesión. */
  unidadX: number;
}

const lineal = ([a, b]: Rango, tamano: number) => (v: number) =>
  ((v - a) / (b - a)) * tamano - tamano / 2;

export function crearMapa(escena: Escena): MapaEjes {
  const { ejes, modo } = escena;
  const ancho = modo === "3d" ? 8 : 10;
  const alto = modo === "3d" ? 5 : 6;
  const fondo = modo === "3d" ? 8 : 0;
  const mx = lineal(ejes.x, ancho);
  const vertical = modo === "3d" ? ejes.z : ejes.y;
  const mv = lineal(vertical, alto);
  const my = lineal(ejes.y, fondo);
  const margen = (vertical[1] - vertical[0]) * 0.02;
  return {
    modo,
    ancho,
    alto,
    fondo,
    ejes,
    punto: (x, y, z = 0) =>
      modo === "3d" ? [mx(x), mv(z), -my(y)] : [mx(x), mv(y), 0],
    altura: mv,
    dentro: (v) => v >= vertical[0] - margen && v <= vertical[1] + margen,
    unidadX: ancho / (ejes.x[1] - ejes.x[0]),
  };
}

/** Marcas «bonitas» (1, 2, 5 × 10ⁿ) para un rango. */
export function marcas([a, b]: Rango, cuantas = 6): number[] {
  const bruto = (b - a) / cuantas;
  const magnitud = 10 ** Math.floor(Math.log10(bruto));
  const paso =
    [1, 2, 5, 10].map((m) => m * magnitud).find((p) => p >= bruto) ?? 10 * magnitud;
  const inicio = Math.ceil(a / paso) * paso;
  const lista: number[] = [];
  for (let v = inicio; v <= b + paso * 1e-9; v += paso) {
    lista.push(Math.abs(v) < paso * 1e-9 ? 0 : Number(v.toPrecision(12)));
  }
  return lista;
}

export function formatear(v: number): string {
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-3 && v !== 0)) return v.toExponential(1);
  return Number(v.toPrecision(4)).toString();
}
