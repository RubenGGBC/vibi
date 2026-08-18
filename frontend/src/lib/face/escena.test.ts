import { afterEach, describe, expect, it } from "vitest";

import { crearEscenaCara, type FaceScene } from "./escena";
import { SENALES_QUIETAS } from "./modificadores";

let escena: FaceScene | null = null;
let contenedor: HTMLElement | null = null;

const montar = (perfil: "web" | "companion" = "companion") => {
  contenedor = document.createElement("div");
  document.body.appendChild(contenedor);
  escena = crearEscenaCara(contenedor, { perfil });
  return { contenedor, escena };
};

afterEach(() => {
  escena?.dispose();
  contenedor?.remove();
  escena = null;
  contenedor = null;
});

describe("montar la escena", () => {
  it("mete un svg en el contenedor", () => {
    const { contenedor } = montar();
    expect(contenedor.querySelector("svg")).not.toBeNull();
  });

  it("dibuja la cara ya en el primer fotograma", () => {
    // Sin esto se ve un hueco vacío hasta el primer `requestAnimationFrame`.
    const { contenedor } = montar();
    const fondo = contenedor.querySelector<SVGPathElement>(".vibi-fondo");
    expect(fondo?.getAttribute("d")).toMatch(/^M/);
  });

  it("perfora los ojos en el cuerpo en vez de dibujarlos encima", () => {
    // Es el modelo de bloub y no un detalle: agujeros en una máscara se
    // recortan solos contra la silueta cuando resbalan hacia el borde.
    const { contenedor } = montar();
    const mascara = contenedor.querySelector("mask");
    expect(mascara).not.toBeNull();
    expect(mascara!.querySelectorAll("path").length).toBeGreaterThan(1);
  });

  it("le pone la antena, que el referente no tiene", () => {
    const { contenedor } = montar();
    expect(contenedor.querySelector(".vibi-tallo")?.getAttribute("d")).toMatch(/^M/);
    expect(contenedor.querySelector(".vibi-bola")).not.toBeNull();
  });

  it("da al svg un sistema de coordenadas propio para que escale solo", () => {
    // Con `viewBox` el redimensionado es cosa del navegador, no nuestra.
    const { contenedor } = montar();
    expect(contenedor.querySelector("svg")?.getAttribute("viewBox")).toBeTruthy();
  });

  it("no se anuncia a los lectores de pantalla", () => {
    // Es decoración: lo que Vibi está haciendo se cuenta con texto aparte.
    const { contenedor } = montar();
    expect(contenedor.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("cambiar lo que muestra", () => {
  it("transforma la silueta al cambiar de estado", () => {
    const { contenedor, escena } = montar();
    const fondo = contenedor.querySelector<SVGPathElement>(".vibi-fondo");
    const antes = fondo?.getAttribute("d");
    escena.setState("alert");
    // El bucle vive de `requestAnimationFrame`, que en las pruebas no corre
    // solo; se pide un fotograma a mano.
    escena.dibujar(2);
    expect(fondo?.getAttribute("d")).not.toBe(antes);
  });

  it("acepta señales sin romperse", () => {
    const { escena } = montar();
    expect(() => escena.setSenales({ ...SENALES_QUIETAS, pasos: 6 })).not.toThrow();
  });

  it("acepta el puntero sin romperse", () => {
    const { escena } = montar();
    expect(() => {
      escena.setPointer(0.5, -0.2);
      escena.clearPointer();
    }).not.toThrow();
  });
});

describe("desmontar", () => {
  it("deja el contenedor limpio", () => {
    const { contenedor, escena } = montar();
    escena.dispose();
    expect(contenedor.querySelector("svg")).toBeNull();
  });

  it("aguanta que le sigan hablando después", () => {
    // React puede entregar un cambio de estado entre el desmontaje y la
    // limpieza del efecto.
    const { escena } = montar();
    escena.dispose();
    expect(() => {
      escena.setState("thinking");
      escena.resize();
      escena.dispose();
    }).not.toThrow();
  });
});
