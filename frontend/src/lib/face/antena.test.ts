import { describe, expect, it } from "vitest";

import { ANTENA_REPOSO, LARGO_ANTENA, crearAntena } from "./antena";

const ANCLAJE = { x: 0, y: -0.95 };
const PASO = 1 / 60;

/** Deja la antena asentada, para partir de un estado conocido. */
const asentar = (segundos = 3, estado = ANTENA_REPOSO, anclaje = ANCLAJE) => {
  const antena = crearAntena();
  antena.fijar(estado, anclaje);
  for (let t = 0; t < segundos; t += PASO) antena.avanzar(estado, anclaje, PASO);
  return antena;
};

describe("la antena en reposo", () => {
  it("se queda tiesa encima del anclaje", () => {
    const forma = asentar().avanzar(ANTENA_REPOSO, ANCLAJE, PASO);
    expect(forma.bola.x).toBeCloseTo(0, 3);
    expect(forma.bola.y).toBeCloseTo(ANCLAJE.y - LARGO_ANTENA, 3);
    expect(forma.base).toEqual(ANCLAJE);
  });

  it("pone el codo entre la base y la bola", () => {
    const forma = asentar().avanzar(ANTENA_REPOSO, ANCLAJE, PASO);
    expect(forma.codo.y).toBeLessThan(forma.base.y);
    expect(forma.codo.y).toBeGreaterThan(forma.bola.y);
  });
});

describe("la inercia", () => {
  it("deja la bola atrás cuando la cabeza se mueve de golpe", () => {
    // Es todo el motivo de que la antena exista: cada movimiento del cuerpo la
    // mueve sola, sin que ninguna pose tenga que animarla a mano.
    const antena = asentar();
    const desplazado = { x: 0.8, y: -0.95 };
    const forma = antena.avanzar(ANTENA_REPOSO, desplazado, PASO);
    expect(forma.base.x).toBe(0.8);
    expect(forma.bola.x).toBeLessThan(0.8 * 0.3);
  });

  it("acaba alcanzando a la cabeza si esta se queda quieta", () => {
    const desplazado = { x: 0.8, y: -0.95 };
    const forma = asentar(3, ANTENA_REPOSO, desplazado).avanzar(
      ANTENA_REPOSO,
      desplazado,
      PASO,
    );
    expect(forma.bola.x).toBeCloseTo(0.8, 2);
  });

  it("no se dispara al infinito con un salto de tiempo grande", () => {
    // Volver a una ventana que estuvo minimizada entrega un delta enorme.
    const antena = asentar();
    const forma = antena.avanzar(ANTENA_REPOSO, { x: 2, y: -0.95 }, 4);
    expect(Number.isFinite(forma.bola.x)).toBe(true);
    expect(Math.abs(forma.bola.x)).toBeLessThan(10);
  });
});

describe("lo que la antena sabe decir", () => {
  it("dobla la punta hacia un lado cuando se le pide curva", () => {
    // La interrogación de esperar permiso y la oreja que apunta al escuchar.
    const estado = { ...ANTENA_REPOSO, curva: 60 };
    const forma = asentar(3, estado).avanzar(estado, ANCLAJE, PASO);
    expect(forma.bola.x).toBeGreaterThan(0.2);
    expect(forma.bola.y).toBeGreaterThan(ANCLAJE.y - LARGO_ANTENA);
  });

  it("se recoge del todo cuando el largo baja a cero", () => {
    const estado = { ...ANTENA_REPOSO, largo: 0 };
    const forma = asentar(3, estado).avanzar(estado, ANCLAJE, PASO);
    expect(forma.bola.x).toBeCloseTo(ANCLAJE.x, 2);
    expect(forma.bola.y).toBeCloseTo(ANCLAJE.y, 2);
  });

  it("lleva la bola al destino cuando se suelta del tallo", () => {
    // Pensar y alerta la desprenden: en uno orbita, en el otro baja a ser el
    // punto del signo de admiración.
    const estado = {
      ...ANTENA_REPOSO,
      bolaSuelta: true,
      bolaDestino: { x: 0.4, y: 0.55 },
    };
    const forma = asentar(3, estado).avanzar(estado, ANCLAJE, PASO);
    expect(forma.bola.x).toBeCloseTo(0.4, 2);
    expect(forma.bola.y).toBeCloseTo(0.55, 2);
  });

  it("no teletransporta la bola al soltarla", () => {
    // Tiene que verse el viaje. Si aparece ya abajo, el gesto no se lee.
    const antena = asentar();
    const estado = {
      ...ANTENA_REPOSO,
      bolaSuelta: true,
      bolaDestino: { x: 0, y: 0.55 },
    };
    const forma = antena.avanzar(estado, ANCLAJE, PASO);
    expect(forma.bola.y).toBeLessThan(0);
  });
});

describe("fijar la antena", () => {
  it("la planta en su sitio sin recorrido", () => {
    // Al montar el componente no puede verse la antena viajando desde el origen.
    const antena = crearAntena();
    const forma = antena.fijar(ANTENA_REPOSO, ANCLAJE);
    expect(forma.bola.x).toBeCloseTo(0, 6);
    expect(forma.bola.y).toBeCloseTo(ANCLAJE.y - LARGO_ANTENA, 6);
  });
});
