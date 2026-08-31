import { describe, expect, it } from "vitest";

import { ESTADOS } from "../estados";
import { CATALOGO } from "./formas";
import { GESTOS, REPOSO, gestoDe } from "./gestos";

describe("el reparto de estados", () => {
  it("le da cara a los treinta y dos", () => {
    // Un estado sin entrada caería en `idle` y se vería como el reposo: un
    // error mudo, de los que solo se descubren mirando la ventana un rato.
    for (const estado of ESTADOS) {
      expect(GESTOS[estado], estado).toBeDefined();
    }
    expect(Object.keys(GESTOS)).toHaveLength(ESTADOS.length);
  });

  it("no inventa formas que el catálogo no tenga", () => {
    for (const estado of ESTADOS) {
      const gesto = GESTOS[estado];
      expect(CATALOGO[gesto.ojo], `${estado} ojo`).toBeDefined();
      if (gesto.ojoDer) expect(CATALOGO[gesto.ojoDer], `${estado} ojoDer`).toBeDefined();
    }
  });

  it("completa el porte con el reposo", () => {
    // Los gestos declaran solo lo que cambian; la escena necesita los seis
    // números o se queda leyendo `undefined` y escribiendo NaN en el SVG.
    for (const estado of ESTADOS) {
      const porte = gestoDe(estado).porte;
      for (const clave of Object.keys(REPOSO) as Array<keyof typeof REPOSO>) {
        expect(porte[clave], `${estado}.${clave}`).toBeDefined();
      }
      expect(Number.isFinite(porte.vaiven[0]), estado).toBe(true);
      expect(Number.isFinite(porte.vaiven[1]), estado).toBe(true);
    }
  });

  it("mantiene los números dentro de lo que la escena sabe usar", () => {
    for (const estado of ESTADOS) {
      const { tension, ardor, brinco, garbo } = gestoDe(estado).porte;
      expect(tension, `${estado} tension`).toBeGreaterThanOrEqual(0);
      expect(tension, `${estado} tension`).toBeLessThanOrEqual(1);
      expect(ardor, `${estado} ardor`).toBeGreaterThanOrEqual(0);
      expect(ardor, `${estado} ardor`).toBeLessThanOrEqual(1);
      expect(brinco, `${estado} brinco`).toBeGreaterThanOrEqual(0);
      expect(brinco, `${estado} brinco`).toBeLessThanOrEqual(1);
      // El muelle del sombrero se amortigua con `1.55·√garbo`: en cero no
      // frenaría nunca y la chistera saldría volando.
      expect(garbo, `${estado} garbo`).toBeGreaterThan(20);
    }
  });
});

describe("lo que separa a las que comparten cara", () => {
  it("las cinco de ejecutar llevan el mismo `->` y distinto porte", () => {
    const familia = ["hacking", "launching", "sending", "reaching", "handling"] as const;
    for (const estado of familia) {
      expect(GESTOS[estado].ojo).toBe("guion");
      expect(GESTOS[estado].ojoDer).toBe("punta");
    }
    // Si compartieran también el porte, cinco herramientas muy distintas se
    // verían idénticas, que es justo el problema que la cara vino a arreglar.
    const portes = familia.map((estado) => JSON.stringify(gestoDe(estado).porte));
    expect(new Set(portes).size).toBe(familia.length);
  });

  it("las cinco de buscar llevan la lupa", () => {
    for (const estado of ["searching", "browsing", "rummaging", "peeking", "reading"] as const) {
      expect(GESTOS[estado].complemento, estado).toBe("lupa");
    }
  });

  it("recelar y fallar son los únicos asimétricos", () => {
    // La cuña del recelo mira hacia dentro, así que el ojo derecho es el
    // espejo del izquierdo y no la misma forma repetida.
    const asimetricos = ESTADOS.filter((estado) => {
      const gesto = GESTOS[estado];
      return gesto.ojoDer !== undefined && gesto.ojoDer !== gesto.ojo;
    });
    expect(asimetricos.sort()).toEqual(
      ["fallo", "handling", "hacking", "launching", "reaching", "recelo", "sending"].sort(),
    );
  });

  it("la boca solo sale trabajando", () => {
    const conBoca = ESTADOS.filter((estado) => GESTOS[estado].boca);
    expect(conBoca.sort()).toEqual(
      ["forjando", "noting", "trastienda", "vibing", "working", "writing"].sort(),
    );
  });

  it("apaga el fuego cuando no hay canal", () => {
    // Es lo que separa dormirse de estar quieta: sin servidor no hay nada
    // ardiendo, y el reposo sí arde un poco.
    expect(gestoDe("offline").porte.ardor).toBe(0);
    expect(gestoDe("idle").porte.ardor).toBeGreaterThan(0);
  });
});
