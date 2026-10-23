import { all, create, type EvalFunction } from "mathjs";

import type { Sistema } from "./tipos";

/**
 * Integración en vivo de los sistemas que escribe el agente
 * (`app/estudio/dinamica.py` hace lo mismo en el servidor para validarlos).
 *
 * Las ecuaciones llegan en forma canónica y ya validadas. Se compilan una vez
 * y cada fotograma se avanza con RK4 en pasos fijos de 1/240 s, con el tiempo
 * correcto en cada subpaso por si la ecuación depende de t.
 */
const math = create(all, { number: "number" });
math.import({ ln: (x: number) => Math.log(x) }, { override: true });

export const DT = 1 / 240;
const MAX_PASOS_POR_FOTOGRAMA = 240;

export interface Integrador {
  orden: string[];
  estado: number[];
  t: number;
  roto: boolean;
  /** Avanza `segundos` y devuelve las variables por nombre. */
  avanzar: (segundos: number, valores: Record<string, number>) => Record<string, number>;
  variables: () => Record<string, number>;
}

function numero(valor: unknown): number {
  return typeof valor === "number" ? valor : Number.NaN;
}

export function crearIntegrador(sistema: Sistema, valores: Record<string, number>): Integrador {
  const orden = sistema.orden;
  const derivadas: EvalFunction[] = orden.map((v) => math.compile(sistema.ecuaciones[v]));
  const estado = orden.map((v) => numero(math.evaluate(sistema.iniciales[v], { ...valores })));
  const integrador: Integrador = {
    orden,
    estado,
    t: 0,
    roto: !estado.every(Number.isFinite),
    variables: () => Object.fromEntries(orden.map((v, i) => [v, integrador.estado[i]])),
    avanzar: (segundos, actuales) => {
      if (integrador.roto) return integrador.variables();
      const scope: Record<string, number> = { ...actuales };
      const f = (y: number[], t: number): number[] => {
        orden.forEach((v, i) => {
          scope[v] = y[i];
        });
        scope.t = t;
        return derivadas.map((d) => numero(d.evaluate(scope)));
      };
      const pasos = Math.min(Math.round(segundos / DT), MAX_PASOS_POR_FOTOGRAMA);
      let y = integrador.estado;
      let t = integrador.t;
      for (let p = 0; p < pasos; p += 1) {
        const h = DT;
        const k1 = f(y, t);
        const k2 = f(y.map((v, i) => v + (h / 2) * k1[i]), t + h / 2);
        const k3 = f(y.map((v, i) => v + (h / 2) * k2[i]), t + h / 2);
        const k4 = f(y.map((v, i) => v + h * k3[i]), t + h);
        y = y.map((v, i) => v + (h / 6) * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]));
        t += h;
        if (!y.every((v) => Number.isFinite(v) && Math.abs(v) < 1e9)) {
          // Mismo criterio que el servidor: se para donde deja de existir.
          integrador.roto = true;
          break;
        }
        integrador.estado = y;
        integrador.t = t;
      }
      return integrador.variables();
    },
  };
  return integrador;
}
