import { describe, expect, it } from "vitest";

import { PUNTOS_POR_OJO, crearOjos } from "./ojos";
import { crearSacadas } from "./sacadas";

/** Los números de un trazado SVG, para poder medirlo. */
const puntos = (d: string): number[] =>
  (d.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);

const ancho = (d: string) => {
  const n = puntos(d);
  const xs = n.filter((_, i) => i % 2 === 0);
  return Math.max(...xs) - Math.min(...xs);
};
const alto = (d: string) => {
  const n = puntos(d);
  const ys = n.filter((_, i) => i % 2 === 1);
  return Math.max(...ys) - Math.min(...ys);
};

/** Deja que el morfeo llegue: son 180 ms, así que medio segundo sobra. */
const asentar = (ojos: ReturnType<typeof crearOjos>, forma: Parameters<ReturnType<typeof crearOjos>["trazar"]>[0]) => {
  let d: [string, string] = ["", ""];
  for (let i = 0; i < 40; i += 1) d = ojos.trazar(forma, forma, 1 / 60);
  return d;
};

describe("la forma de los ojos", () => {
  it("todas las formas se muestrean igual, que es lo que deja morfarlas", () => {
    // Si una tuviera otro número de puntos, pasar de una a otra sería un
    // revoltijo en vez de una interpolación.
    const ojos = crearOjos();
    for (const forma of ["pildora", "redondo", "rendija", "contento", "aspa", "dormido"] as const) {
      const [d] = asentar(ojos, forma);
      // Un tramo `Q` por punto, más el `M` inicial.
      expect((d.match(/Q/g) ?? []).length).toBe(PUNTOS_POR_OJO);
    }
  });

  it("una rendija es ancha y baja, y un ojo alto es lo contrario", () => {
    const a = asentar(crearOjos(), "rendija")[0];
    const b = asentar(crearOjos(), "alto")[0];
    expect(ancho(a)).toBeGreaterThan(alto(a) * 2);
    expect(alto(b)).toBeGreaterThan(ancho(b) * 2);
  });

  it("el arco de contento va hacia arriba y el de tristón hacia abajo", () => {
    // Es la diferencia entre las dos, y si se invirtiera nadie lo notaría
    // leyendo el código: por eso se comprueba.
    const centroide = (d: string) => {
      const n = puntos(d);
      const ys = n.filter((_, i) => i % 2 === 1);
      return ys.reduce((s, v) => s + v, 0) / ys.length;
    };
    expect(centroide(asentar(crearOjos(), "contento")[0]))
      .toBeLessThan(centroide(asentar(crearOjos(), "triston")[0]));
  });

  it("cambiar de forma es un camino, no un salto", () => {
    const ojos = crearOjos();
    asentar(ojos, "redondo");
    const antes = ancho(ojos.trazar("redondo", "redondo", 0)[0]);
    const unPaso = ancho(ojos.trazar("rendija", "rendija", 1 / 60)[0]);
    const alFinal = ancho(asentar(ojos, "rendija")[0]);
    // Un fotograma después va camino de la rendija, pero todavía no ha llegado.
    expect(unPaso).not.toBeCloseTo(antes, 1);
    expect(Math.abs(unPaso - alFinal)).toBeGreaterThan(0.5);
  });

  it("los dos ojos pueden llevar formas distintas", () => {
    // Recelar es exactamente eso: uno abierto y el otro entornado.
    const ojos = crearOjos();
    let d: [string, string] = ["", ""];
    for (let i = 0; i < 40; i += 1) d = ojos.trazar("redondo", "rendija", 1 / 60);
    expect(alto(d[0])).toBeGreaterThan(alto(d[1]) * 2);
  });
});

describe("las sacadas", () => {
  it("no propone nada mientras toca estar quieta", () => {
    // Es lo que evita que la escena llame a `setLook` en cada fotograma: si lo
    // hiciera, reiniciaría la transición y el ojo no llegaría nunca.
    const s = crearSacadas(() => 0.5);
    expect(s.avanzar("lenta", 0)).not.toBeNull();
    expect(s.avanzar("lenta", 1 / 60)).toBeNull();
  });

  it("la nerviosa salta muchas más veces que la lenta", () => {
    const contar = (temperamento: Parameters<ReturnType<typeof crearSacadas>["avanzar"]>[0]) => {
      const s = crearSacadas(() => 0.5);
      let n = 0;
      for (let i = 0; i < 600; i += 1) if (s.avanzar(temperamento, 1 / 60)) n += 1;
      return n;
    };
    expect(contar("nerviosa")).toBeGreaterThan(contar("lenta") * 5);
  });

  it("la pegada vuelve siempre a ti", () => {
    // `vuelve: 1` significa que el centro gana siempre, y el centro eres tú.
    const s = crearSacadas(() => 0.5);
    for (let i = 0; i < 8; i += 1) {
      const salto = s.avanzar("pegada", 3);
      if (salto) expect(salto).toEqual({ yaw: 0, pitch: 0 });
    }
  });

  it("leer avanza por renglones y hace el retorno de carro", () => {
    const s = crearSacadas(() => 0.5);
    const xs: number[] = [];
    for (let i = 0; i < 400 && xs.length < 7; i += 1) {
      const salto = s.avanzar("renglon", 1 / 60);
      if (salto) xs.push(salto.yaw);
    }
    // Cinco saltos subiendo hasta el final del renglón...
    for (let i = 1; i < 5; i += 1) expect(xs[i]).toBeGreaterThan(xs[i - 1]);
    // ...y el sexto es el retorno de carro: se va al principio de golpe.
    expect(xs[5]).toBeLessThan(xs[0]);
  });

  it("al cambiar de gesto la mirada salta ya, sin esperar al anterior", () => {
    const s = crearSacadas(() => 0.5);
    s.avanzar("lenta", 0);
    expect(s.avanzar("lenta", 1 / 60)).toBeNull();
    s.reiniciar();
    expect(s.avanzar("lenta", 1 / 60)).not.toBeNull();
  });
});
