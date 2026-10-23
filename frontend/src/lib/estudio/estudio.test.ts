import { describe, expect, it } from "vitest";

import { crearMapa, marcas } from "./ejes";
import { evaluar } from "./expr";
import { avanzar, pendulo, periodoPendulo, proyectil } from "./fisica";
import { crearIntegrador } from "./dinamica";
import { colocableAMano, rama, redondear } from "./manipulacion";
import type { Escena, Funcion, Objeto, Sistema } from "./tipos";
import { estadoDePaso, valoresIniciales } from "./visibilidad";

function escena(parcial: Partial<Escena> = {}): Escena {
  return {
    version: 1,
    titulo: "Prueba",
    modo: "2d",
    ejes: { visibles: true, x: [0, 10], y: [0, 5], z: [-1, 1] },
    parametros: [],
    elementos: [],
    pasos: [],
    paso_actual: 0,
    actualizada_en: null,
    ...parcial,
  };
}

const elemento = (id: string): Funcion => ({
  id,
  tipo: "funcion",
  expresion: "x",
  variable: "x",
  dominio: null,
  etiqueta: id,
  color: "#fff",
  usa: [],
  procedencia: { origen: "engine", detalle: "" },
});

describe("expresiones", () => {
  it("evalúa la forma canónica del servidor", () => {
    expect(evaluar("x ^ 2 + 1", { x: 3 })).toBe(10);
    expect(evaluar("ln(e)", {})).toBeCloseTo(1);
  });

  it("lo que no es un número real es NaN, como en el servidor", () => {
    expect(evaluar("sqrt(x)", { x: -1 })).toBeNaN();
    expect(evaluar("log(x)", { x: -2 })).toBeNaN();
  });
});

describe("pasos", () => {
  const conPasos = escena({
    elementos: [elemento("a"), elemento("b"), elemento("c")],
    pasos: [
      { texto: "1", mostrar: [], ocultar: [], resaltar: ["a"], pregunta: null },
      { texto: "2", mostrar: ["b"], ocultar: [], resaltar: [], pregunta: null },
      { texto: "3", mostrar: ["c"], ocultar: ["a"], resaltar: ["c.parte"], pregunta: null },
    ],
  });

  it("lo que aparece por primera vez en un mostrar espera a su paso", () => {
    expect([...estadoDePaso(conPasos, 0).visibles].sort()).toEqual(["a"]);
    expect([...estadoDePaso(conPasos, 1).visibles].sort()).toEqual(["a", "b"]);
    expect([...estadoDePaso(conPasos, 2).visibles].sort()).toEqual(["b", "c"]);
  });

  it("resaltar dura su paso y separa las partes", () => {
    expect([...estadoDePaso(conPasos, 0).resaltados]).toEqual(["a"]);
    expect(estadoDePaso(conPasos, 1).resaltados.size).toBe(0);
    expect(estadoDePaso(conPasos, 2).partes.get("c")).toEqual(["parte"]);
  });

  it("sin pasos se ve todo", () => {
    const sin = escena({ elementos: [elemento("a")] });
    expect([...estadoDePaso(sin, 0).visibles]).toEqual(["a"]);
  });
});

describe("deslizadores", () => {
  it("conserva lo que movió el alumno si sigue en rango", () => {
    const e = escena({
      parametros: [{ id: "N", etiqueta: "N", minimo: 1, maximo: 10, paso: 1, valor: 3 }],
    });
    expect(valoresIniciales(e, { N: 7 })).toEqual({ N: 7 });
    expect(valoresIniciales(e, { N: 70 })).toEqual({ N: 3 });
  });
});

describe("ejes", () => {
  it("marcas redondas", () => {
    expect(marcas([0, 10])).toEqual([0, 2, 4, 6, 8, 10]);
    expect(marcas([-1, 1], 4)).toEqual([-1, -0.5, 0, 0.5, 1]);
  });

  it("la caja 2D va de esquina a esquina", () => {
    const mapa = crearMapa(escena());
    expect(mapa.punto(0, 0)).toEqual([-5, -3, 0]);
    expect(mapa.punto(10, 5)).toEqual([5, 3, 0]);
  });

  it("en 3D la z es la altura", () => {
    const mapa = crearMapa(escena({ modo: "3d", ejes: { visibles: true, x: [-1, 1], y: [-1, 1], z: [-1, 1] } }));
    const [, alto, hondo] = mapa.punto(0, 1, 1);
    expect(alto).toBeCloseTo(2.5);
    expect(hondo).toBeCloseTo(-4);
  });
});

describe("física", () => {
  it("el péndulo integrado conserva la energía sin rozamiento", () => {
    const L = 1;
    const g = 9.81;
    const energia = ([t, w]: number[]) => 0.5 * L * L * w * w + g * L * (1 - Math.cos(t));
    let estado = [0.5, 0];
    const inicial = energia(estado);
    for (let i = 0; i < 20; i += 1) estado = avanzar(estado, pendulo(L, g, 0), 0.5);
    expect(energia(estado)).toBeCloseTo(inicial, 5);
  });

  it("el periodo exacto coincide con el del servidor", () => {
    expect(periodoPendulo(1, 9.81, 90) / (2 * Math.PI * Math.sqrt(1 / 9.81))).toBeCloseTo(1.18, 2);
  });

  it("el proyectil cae donde dice la fórmula", () => {
    const tiro = proyectil(20, 30, 9.81, 0);
    expect(tiro.alcance).toBeCloseTo((400 * Math.sin(Math.PI / 3)) / 9.81, 6);
    expect(tiro.posicion(tiro.tiempo)[1]).toBeCloseTo(0, 6);
  });
});

describe("sistemas dinámicos", () => {
  const sistema = (ecuaciones: Record<string, string>, iniciales: Record<string, string>): Sistema => ({
    id: "s",
    tipo: "sistema",
    orden: Object.keys(ecuaciones),
    iniciales,
    ecuaciones,
    grafica: false,
    etiqueta: "s",
    color: "#fff",
    usa: [],
    procedencia: { origen: "modelo", detalle: "" },
  });

  it("integra un oscilador como el servidor", () => {
    const integrador = crearIntegrador(sistema({ x: "v", v: "-k * x" }, { x: "1", v: "0" }), { k: 4 });
    // Medio periodo de cos(2t): x(π/2) = -1.
    let t = 0;
    let x = 1;
    while (t < Math.PI / 2 - 1e-9) {
      const paso = Math.min(0.5, Math.PI / 2 - t);
      x = integrador.avanzar(paso, { k: 4 }).x;
      t += paso;
    }
    expect(x).toBeCloseTo(-1, 2);
  });

  it("se detiene si el sistema diverge", () => {
    const integrador = crearIntegrador(sistema({ u: "u ^ 2" }, { u: "1" }), {});
    for (let i = 0; i < 10; i += 1) integrador.avanzar(0.5, {});
    expect(integrador.roto).toBe(true);
    expect(integrador.t).toBeLessThan(1.01);
  });
});

describe("manipular objetos", () => {
  const objeto = (id: string, extra: Partial<Objeto> = {}): Objeto => ({
    id,
    tipo: "objeto",
    etiqueta: id,
    color: "#fff",
    usa: [],
    procedencia: { origen: "modelo", detalle: "" },
    forma: "esfera",
    padre: null,
    posicion: ["0", "1.5", "-2e-3"],
    rotacion: ["0", "0", "0"],
    escala: ["1", "1", "1"],
    tamano: ["0.5"],
    opacidad: 1,
    brillo: 0,
    estela: 0,
    anima: false,
    ...extra,
  });

  it("solo coloca a mano lo que no se anima", () => {
    expect(colocableAMano(objeto("a"))).toBe(true);
    expect(colocableAMano(objeto("b", { posicion: ["cos(t)", "0", "0"] }))).toBe(false);
    expect(colocableAMano(objeto("c", { escala: ["k", "1", "1"] }))).toBe(false);
  });

  it("aislar incluye lo que cuelga del objeto", () => {
    const objetos = [objeto("sol"), objeto("tierra", { padre: "sol" }), objeto("luna", { padre: "tierra" }), objeto("marte")];
    expect([...rama("tierra", objetos)].sort()).toEqual(["luna", "tierra"]);
    expect(rama("sol", objetos).size).toBe(3);
  });

  it("redondea lo que deja el gizmo", () => {
    expect(redondear(89.99999, 2)).toBe(90);
    expect(Object.is(redondear(-0.00001, 3), 0)).toBe(true);
  });
});
