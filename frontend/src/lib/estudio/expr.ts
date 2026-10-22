import { all, create, type EvalFunction } from "mathjs";

/**
 * Las fórmulas de la escena, evaluadas aquí para que mover un deslizador no
 * tenga que ir al servidor.
 *
 * Llegan ya validadas y en forma canónica (`app/estudio/expresiones.py`), así
 * que este módulo no filtra nada: compila con mathjs, guarda la compilación y
 * convierte en `NaN` todo lo que no sea un número real (un complejo, un error
 * de dominio), igual que hace el servidor.
 */

const math = create(all, { number: "number" });
math.import({ ln: (x: number) => Math.log(x) }, { override: true });

const cache = new Map<string, EvalFunction | null>();

function compilada(fuente: string): EvalFunction | null {
  if (!cache.has(fuente)) {
    try {
      cache.set(fuente, math.compile(fuente));
    } catch {
      cache.set(fuente, null);
    }
  }
  return cache.get(fuente) ?? null;
}

export function evaluar(fuente: string, scope: Record<string, number>): number {
  const funcion = compilada(fuente);
  if (!funcion) return Number.NaN;
  try {
    // mathjs escribe en el scope si la fórmula asigna; se le da una copia.
    const valor: unknown = funcion.evaluate({ ...scope });
    return typeof valor === "number" ? valor : Number.NaN;
  } catch {
    return Number.NaN;
  }
}

/** Una función de una variable, lista para muestrear. */
export function funcionDe(
  fuente: string,
  variable: string,
  scope: Record<string, number>,
): (x: number) => number {
  const funcion = compilada(fuente);
  const local: Record<string, number> = { ...scope };
  return (x: number) => {
    if (!funcion) return Number.NaN;
    local[variable] = x;
    try {
      const valor: unknown = funcion.evaluate(local);
      return typeof valor === "number" ? valor : Number.NaN;
    } catch {
      return Number.NaN;
    }
  };
}

export const esFinito = (v: number): boolean => Number.isFinite(v);
