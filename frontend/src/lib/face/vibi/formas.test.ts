import { describe, expect, it } from "vitest";

import { CATALOGO, PUNTOS_POR_FORMA, crearOjos, trazarContorno, type FormaOjo } from "./formas";

const NOMBRES = Object.keys(CATALOGO) as FormaOjo[];

/** Área con signo. El signo dice hacia dónde gira el contorno. */
const giro = (pts: ReadonlyArray<{ x: number; y: number }>): number =>
  pts.reduce((suma, a, i) => {
    const b = pts[(i + 1) % pts.length];
    return suma + (a.x * b.y - b.x * a.y);
  }, 0);

describe("el catálogo de formas", () => {
  it("muestrea todas con el mismo número de puntos", () => {
    // Es la condición de la que cuelga todo el morfeo: sin ella no hay
    // correspondencia punto a punto y pasar de una píldora a un chevrón daría
    // un revoltijo en vez de una transformación.
    for (const nombre of NOMBRES) {
      expect(CATALOGO[nombre], nombre).toHaveLength(PUNTOS_POR_FORMA);
    }
  });

  it("las recorre todas en el mismo sentido", () => {
    // La otra mitad de la condición, y la que se rompe sin avisar: dos formas
    // con los mismos puntos pero giradas al revés se desenrollan al morfar, y
    // eso se ve como un latigazo de dos décimas que nadie sabe de dónde sale.
    const sentidos = NOMBRES.map((nombre) => Math.sign(giro(CATALOGO[nombre])));
    expect(new Set(sentidos).size, `sentidos: ${NOMBRES.map((n, i) => `${n}=${sentidos[i]}`).join(", ")}`).toBe(1);
  });

  it("ninguna se queda degenerada", () => {
    for (const nombre of NOMBRES) {
      expect(Math.abs(giro(CATALOGO[nombre])), nombre).toBeGreaterThan(50);
    }
  });

  it("las centra en el anclaje del ojo", () => {
    // La escena solo traslada y escala; si una forma viene descentrada, ese
    // ojo se dibuja fuera de sitio y no hay dónde corregirlo.
    for (const nombre of NOMBRES) {
      const xs = CATALOGO[nombre].map((p) => p.x);
      const ys = CATALOGO[nombre].map((p) => p.y);
      const centroX = (Math.min(...xs) + Math.max(...xs)) / 2;
      const centroY = (Math.min(...ys) + Math.max(...ys)) / 2;
      expect(Math.abs(centroX), `${nombre} en x`).toBeLessThan(6);
      expect(Math.abs(centroY), `${nombre} en y`).toBeLessThan(6);
    }
  });
});

describe("el trazado", () => {
  it("cierra el contorno", () => {
    const d = trazarContorno(CATALOGO.pildora);
    expect(d.startsWith("M")).toBe(true);
    expect(d.endsWith("Z")).toBe(true);
  });

  it("no escupe NaN", () => {
    for (const nombre of NOMBRES) {
      expect(trazarContorno(CATALOGO[nombre]), nombre).not.toMatch(/NaN/);
    }
  });
});

describe("el morfeo", () => {
  it("llega a la forma nueva y se queda", () => {
    const ojos = crearOjos();
    const destino = trazarContorno(CATALOGO.redondo);
    let ultimo = "";
    for (let i = 0; i < 200; i += 1) ultimo = ojos.trazar("redondo", "redondo", 1 / 60)[0];
    expect(ultimo).toBe(destino);
  });

  it("pasa por el medio en vez de saltar", () => {
    // Un cambio de golpe daría el trazado de destino en el primer fotograma.
    const ojos = crearOjos();
    const [primero] = ojos.trazar("punta", "punta", 1 / 60);
    expect(primero).not.toBe(trazarContorno(CATALOGO.punta));
    expect(primero).not.toBe(trazarContorno(CATALOGO.pildora));
  });

  it("no depende de la cadencia para llegar a tiempo", () => {
    // La cara baja a 24 fotogramas en reposo. Si el morfeo avanzara por
    // fotograma en vez de por reloj, ahí tardaría dos veces y media más.
    const rapido = crearOjos();
    const lento = crearOjos();
    for (let i = 0; i < 30; i += 1) rapido.trazar("alegre", "alegre", 1 / 60);
    for (let i = 0; i < 12; i += 1) lento.trazar("alegre", "alegre", 1 / 24);
    const [a] = rapido.trazar("alegre", "alegre", 0);
    const [b] = lento.trazar("alegre", "alegre", 0);
    const numeros = (d: string) => d.match(/-?\d+\.\d+/g)!.map(Number);
    const ma = numeros(a);
    const mb = numeros(b);
    for (let i = 0; i < ma.length; i += 1) expect(Math.abs(ma[i] - mb[i])).toBeLessThan(1.5);
  });

  it("aguanta un delta absurdo sin desbocarse", () => {
    // Volver de una ventana minimizada entrega un salto de segundos.
    const ojos = crearOjos();
    expect(ojos.trazar("furia", "furiaDer", 9)[0]).not.toMatch(/NaN/);
  });
});
