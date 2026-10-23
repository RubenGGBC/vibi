import type { Escena } from "./tipos";

/**
 * Qué se ve y qué se resalta en un paso. Es la misma regla que
 * `escena.visibles_en` en el servidor, que es la que el modelo recibe al crear
 * cada paso:
 *
 * - Un elemento que se nombra por primera vez en un `mostrar` está oculto
 *   hasta ese paso; el resto se ve desde el principio.
 * - Cada paso aplica sus `mostrar` y `ocultar` sobre lo que dejó el anterior.
 * - `resaltar` solo dura su paso. `elemento.parte` resalta una parte de un
 *   modelo y cuenta como resaltar el elemento.
 */
export interface EstadoDePaso {
  visibles: Set<string>;
  resaltados: Set<string>;
  partes: Map<string, string[]>;
}

export function estadoDePaso(escena: Escena, indice: number): EstadoDePaso {
  const ids = escena.elementos.map((e) => e.id);
  const pasos = escena.pasos;
  if (pasos.length === 0) {
    return { visibles: new Set(ids), resaltados: new Set(), partes: new Map() };
  }
  const i = Math.min(Math.max(indice, 0), pasos.length - 1);
  const primera = new Map<string, "mostrar" | "ocultar">();
  for (const paso of pasos) {
    for (const clave of ["mostrar", "ocultar"] as const) {
      for (const ref of paso[clave]) {
        if (!primera.has(ref)) primera.set(ref, clave);
      }
    }
  }
  const visibles = new Set(ids.filter((id) => primera.get(id) !== "mostrar"));
  for (const paso of pasos.slice(0, i + 1)) {
    paso.mostrar.forEach((id) => visibles.add(id));
    paso.ocultar.forEach((id) => visibles.delete(id));
  }
  const resaltados = new Set<string>();
  const partes = new Map<string, string[]>();
  for (const ref of pasos[i].resaltar) {
    const [base, parte] = ref.split(/\.(.*)/s, 2);
    resaltados.add(base);
    if (parte) partes.set(base, [...(partes.get(base) ?? []), parte]);
  }
  const existentes = new Set(ids);
  return {
    visibles: new Set([...visibles].filter((id) => existentes.has(id))),
    resaltados,
    partes,
  };
}

/** Los valores de los deslizadores: los del alumno si siguen siendo válidos. */
export function valoresIniciales(
  escena: Escena,
  previos: Record<string, number>,
): Record<string, number> {
  const valores: Record<string, number> = {};
  for (const parametro of escena.parametros) {
    const previo = previos[parametro.id];
    valores[parametro.id] =
      previo !== undefined && previo >= parametro.minimo && previo <= parametro.maximo
        ? previo
        : parametro.valor;
  }
  return valores;
}

/** Un parámetro de simulación: un número o el id de un deslizador. */
export function resolverNumero(
  valor: number | string,
  valores: Record<string, number>,
): number {
  return typeof valor === "number" ? valor : valores[valor] ?? Number.NaN;
}
