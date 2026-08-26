import { describe, expect, it } from "vitest";

import { PROFILE_SAMPLES } from "./bloub/profiles";
import { ESTADOS } from "./estados";
import { crearLiquido } from "./liquido";
import { cuerpoDe } from "./puente";
import { callarOido, nivelDeVoz, normalizarNivel, publicarNivelDeVoz } from "./oido";

const maximo = (radios: number[]) => Math.max(...radios);

describe("el cuerpo líquido", () => {
  it("devuelve el mismo perfil polar que el motor espera", () => {
    // Es lo que permite entrar por `setShape` sin tocar bloub: mismas muestras,
    // mismos ángulos.
    const radios = crearLiquido().perfil(0, 0, 0);
    expect(radios).toHaveLength(PROFILE_SAMPLES);
    expect(radios.every((r) => Number.isFinite(r) && r > 0)).toBe(true);
  });

  it("cambia de forma con el tiempo", () => {
    const liquido = crearLiquido();
    const a = liquido.perfil(0, 0, 0);
    const b = liquido.perfil(3.7, 0, 1 / 60);
    expect(a).not.toEqual(b);
  });

  it("ningún gesto se sale de la ventana", () => {
    // El techo no es un número redondo: es el viewBox. La cara se dibuja en
    // 274 px para 316 unidades, así que un radio de 1,84 llega justo al borde
    // de los 320 px de la ventana. Medido, no supuesto — la primera versión de
    // esto dejaba `browsing` en 2,14, o sea 380 px de ancho y recortado.
    const TECHO = 1.84;
    for (const estado of ESTADOS) {
      const liquido = crearLiquido();
      let pico = 0;
      for (let i = 0; i < 900; i += 1) {
        pico = Math.max(pico, maximo(liquido.perfil(i / 60, 1, 1 / 60, cuerpoDe(estado))));
      }
      expect(pico, `el gesto «${estado}» se sale`).toBeLessThan(TECHO);
    }
  });

  it("estirarse cambia la forma, no el tamaño", () => {
    // Conservar el volumen es lo correcto en animación y además es lo que
    // impide que una combinación de palancas infle la cara.
    const media = (r: number[]) => r.reduce((a, b) => a + b, 0) / r.length;
    const quieta = crearLiquido().perfil(2, 0, 1 / 60, cuerpoDe("idle"));
    const estirada = crearLiquido().perfil(2, 0, 1 / 60, cuerpoDe("browsing"));
    expect(media(estirada)).toBeCloseTo(media(quieta), 2);
    // Pero la silueta sí es otra: ancha y achatada.
    expect(maximo(estirada)).toBeGreaterThan(maximo(quieta));
  });

  it("siempre es una sola pieza", () => {
    // La gota ancla del centro es lo que lo garantiza: ningún ángulo puede
    // quedarse sin cuerpo por mucho que las otras se separen.
    const liquido = crearLiquido();
    for (let t = 0; t < 40; t += 1.3) {
      const radios = liquido.perfil(t, 0, 1 / 60);
      expect(Math.min(...radios)).toBeGreaterThan(0.4);
    }
  });

  it("se eriza cuando le hablas y se calma cuando callas", () => {
    const liquido = crearLiquido();
    let callado = 0;
    for (let i = 0; i < 40; i += 1) callado = maximo(liquido.perfil(i / 60, 0, 1 / 60));

    const hablando = crearLiquido();
    let alto = 0;
    for (let i = 0; i < 40; i += 1) alto = maximo(hablando.perfil(i / 60, 1, 1 / 60));
    expect(alto).toBeGreaterThan(callado);

    // Y vuelve: la caída es lenta a propósito, así que se le dan dos segundos.
    let vuelta = alto;
    for (let i = 40; i < 200; i += 1) vuelta = maximo(hablando.perfil(i / 60, 0, 1 / 60));
    expect(vuelta).toBeLessThan(alto);
  });

  it("la onda viaja al mismo ritmo aunque cambie la cadencia de dibujo", () => {
    // La cara pinta a 24 en reposo y a 60 trabajando. Si el eco avanzara por
    // fotograma, la onda correría al doble en cuanto se pusiera a trabajar.
    const lento = crearLiquido();
    const rapido = crearLiquido();
    for (let i = 0; i < 24; i += 1) lento.perfil(i / 24, 1, 1 / 24);
    for (let i = 0; i < 60; i += 1) rapido.perfil(i / 60, 1, 1 / 60);
    // Un segundo de voz en los dos: el relieve tiene que ser comparable.
    const a = maximo(lento.perfil(1, 1, 1 / 24));
    const b = maximo(rapido.perfil(1, 1, 1 / 60));
    expect(Math.abs(a - b)).toBeLessThan(0.05);
  });

  it("aguanta un delta absurdo sin deformarse", () => {
    // Volver a una ventana minimizada da saltos de segundos. Es el mismo
    // problema que ya tuvo la antena.
    const liquido = crearLiquido();
    const radios = liquido.perfil(4, 1, 4);
    expect(radios.every((r) => Number.isFinite(r))).toBe(true);
    expect(maximo(radios)).toBeLessThan(1.3);
  });
});

describe("lo que Vibi oye", () => {
  it("descarta la habitación y satura al hablar alto", () => {
    expect(normalizarNivel(0)).toBe(0);
    expect(normalizarNivel(0.028)).toBe(0);
    expect(normalizarNivel(0.9)).toBe(1);
    expect(normalizarNivel(0.124)).toBeCloseTo(0.5, 1);
  });

  it("no se traga un número roto", () => {
    // Un `AudioContext` recién cerrado ha devuelto NaN alguna vez, y un NaN
    // aquí se propagaría a todos los radios del contorno.
    expect(normalizarNivel(NaN)).toBe(0);
  });

  it("se calla al soltar el micrófono", () => {
    publicarNivelDeVoz(0.15);
    expect(nivelDeVoz()).toBeGreaterThan(0);
    callarOido();
    expect(nivelDeVoz()).toBe(0);
  });
});
