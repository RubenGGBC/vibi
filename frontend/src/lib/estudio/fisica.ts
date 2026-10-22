/**
 * La integración de los modelos de `app/estudio/fisica.py`, fotograma a
 * fotograma. Funciones puras: estado y parámetros entran, estado sale.
 *
 * Se integra con RK4 en subpasos fijos de 1/240 s, independientes de los FPS:
 * un portátil a 30 FPS y un monitor a 144 ven el mismo péndulo.
 */

export const DT = 1 / 240;

type Derivada = (y: number[]) => number[];

function rk4(y: number[], f: Derivada, h: number): number[] {
  const k1 = f(y);
  const k2 = f(y.map((v, i) => v + (h / 2) * k1[i]));
  const k3 = f(y.map((v, i) => v + (h / 2) * k2[i]));
  const k4 = f(y.map((v, i) => v + h * k3[i]));
  return y.map((v, i) => v + (h / 6) * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]));
}

/** Avanza `segundos` de tiempo real en subpasos fijos. */
export function avanzar(
  estado: number[],
  f: Derivada,
  segundos: number,
): number[] {
  // Si la pestaña estuvo en segundo plano llega un salto enorme: se recorta
  // para no congelar el navegador recuperando minutos de simulación.
  const pasos = Math.min(Math.round(segundos / DT), 240);
  let y = estado;
  for (let i = 0; i < pasos; i += 1) y = rk4(y, f, DT);
  return y;
}

/** [θ, ω] */
export function pendulo(longitud: number, g: number, c: number): Derivada {
  return ([theta, omega]) => [omega, -(g / longitud) * Math.sin(theta) - c * omega];
}

/** [x, v] */
export function muelle(m: number, k: number, c: number): Derivada {
  return ([x, v]) => [v, (-k * x - c * v) / m];
}

export interface Tiro {
  tiempo: number;
  alcance: number;
  alturaMaxima: number;
  posicion: (t: number) => [number, number];
}

export function proyectil(v: number, anguloGrados: number, g: number, h0: number): Tiro {
  const a = (anguloGrados * Math.PI) / 180;
  const vx = v * Math.cos(a);
  const vy = v * Math.sin(a);
  const tiempo = (vy + Math.sqrt(vy * vy + 2 * g * h0)) / g;
  return {
    tiempo,
    alcance: vx * tiempo,
    alturaMaxima: h0 + (vy * vy) / (2 * g),
    posicion: (t) => [vx * t, h0 + vy * t - 0.5 * g * t * t],
  };
}

export function onda(
  amplitud: number,
  longitudOnda: number,
  frecuencia: number,
): (x: number, t: number) => number {
  const k = (2 * Math.PI) / longitudOnda;
  const w = 2 * Math.PI * frecuencia;
  return (x, t) => amplitud * Math.sin(k * x - w * t);
}

/** Periodo del péndulo ideal a cualquier amplitud: 4·√(L/g)·K(sin(θ₀/2)). */
export function periodoPendulo(longitud: number, g: number, anguloGrados: number): number {
  const k = Math.sin((anguloGrados * Math.PI) / 360);
  let a = 1;
  let b = Math.sqrt(1 - k * k);
  for (let i = 0; i < 40 && Math.abs(a - b) > 1e-15; i += 1) {
    [a, b] = [(a + b) / 2, Math.sqrt(a * b)];
  }
  return 4 * Math.sqrt(longitud / g) * (Math.PI / (2 * a));
}
