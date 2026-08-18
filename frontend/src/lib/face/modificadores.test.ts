import { describe, expect, it } from "vitest";

import {
  MAX_PASOS,
  MAX_PENDIENTES,
  SENALES_QUIETAS,
  ajustesDe,
} from "./modificadores";

const AHORA = 1_000_000;
const con = (parcial: Partial<typeof SENALES_QUIETAS>) =>
  ajustesDe({ ...SENALES_QUIETAS, ...parcial }, AHORA);

describe("sin nada que contar", () => {
  it("no toca nada", () => {
    const ajustes = ajustesDe(SENALES_QUIETAS, AHORA);
    expect(ajustes.cargaBola).toBe(1);
    expect(ajustes.brilloBola).toBe(1);
    expect(ajustes.inclinacionRemota).toBe(0);
    expect(ajustes.puntosPendientes).toBe(0);
    expect(ajustes.impulsoCorte).toBe(0);
  });
});

describe("el lastre del turno", () => {
  it("carga la bola según se encadenan pasos", () => {
    // Es feedback que hoy no se ve en ninguna pantalla: si el turno va por el
    // paso uno o por el doce.
    expect(con({ pasos: 4 }).cargaBola).toBeGreaterThan(con({ pasos: 1 }).cargaBola);
    expect(con({ pasos: 10 }).cargaBola).toBeGreaterThan(con({ pasos: 4 }).cargaBola);
  });

  it("satura para que un turno largo no infle la bola sin fin", () => {
    expect(con({ pasos: 40 }).cargaBola).toBeCloseTo(con({ pasos: MAX_PASOS }).cargaBola, 9);
  });

  it("acelera el latido con los pasos", () => {
    expect(con({ pasos: 10 }).latidoBola).toBeGreaterThan(con({ pasos: 0 }).latidoBola);
  });
});

describe("el latido de los tokens", () => {
  it("se queda quieto cuando no llega nada", () => {
    // La quietud ES la información: el modelo está atascado.
    expect(con({ cadencia: 0 }).pulsoHabla).toBe(0);
  });

  it("sube con el caudal de deltas", () => {
    expect(con({ cadencia: 25 }).pulsoHabla).toBeGreaterThan(con({ cadencia: 5 }).pulsoHabla);
  });

  it("no pasa de uno por muy rápido que hable", () => {
    expect(con({ cadencia: 500 }).pulsoHabla).toBeLessThanOrEqual(1);
  });
});

describe("el piloto del canal", () => {
  it("apaga la bola de forma progresiva según se retrasa el pong", () => {
    // El aviso tiene que llegar antes de que el canal se declare caído.
    const brillos = [0, 1500, 3000, 4500, 6000].map((ms) => con({ retrasoCanal: ms }).brilloBola);
    for (let i = 1; i < brillos.length; i += 1) {
      expect(brillos[i]).toBeLessThan(brillos[i - 1]);
    }
    expect(brillos[0]).toBe(1);
  });

  it("arrastra el latido cuando el canal se retrasa", () => {
    expect(con({ retrasoCanal: 5000 }).latidoBola).toBeLessThan(
      con({ retrasoCanal: 0 }).latidoBola,
    );
  });

  it("no baja del suelo por mucho que tarde", () => {
    expect(con({ retrasoCanal: 60_000 }).brilloBola).toBeGreaterThanOrEqual(0);
  });
});

describe("ejecutar en otro equipo", () => {
  it("no inclina nada cuando el trabajo es de casa", () => {
    expect(con({ remoto: null }).inclinacionRemota).toBe(0);
  });

  it("inclina hacia fuera cuando manda a otro equipo", () => {
    expect(con({ remoto: "sobremesa" }).inclinacionRemota).toBeGreaterThan(0);
  });

  it("inclina igual sea cual sea el equipo", () => {
    // La dirección es convencional: no sabemos dónde está el otro equipo, y
    // fingir que sí sería inventarse información.
    expect(con({ remoto: "sobremesa" }).inclinacionRemota).toBe(
      con({ remoto: "portatil" }).inclinacionRemota,
    );
  });
});

describe("los permisos que esperan", () => {
  it("pone un punto por orden pendiente", () => {
    expect(con({ pendientes: 3 }).puntosPendientes).toBe(3);
  });

  it("deja de añadir puntos pasado el tope", () => {
    expect(con({ pendientes: 30 }).puntosPendientes).toBe(MAX_PENDIENTES);
  });
});

describe("el corte hacia una herramienta", () => {
  it("da el impulso entero en el instante del corte", () => {
    expect(con({ corte: AHORA }).impulsoCorte).toBeCloseTo(1, 6);
  });

  it("lo va gastando", () => {
    expect(con({ corte: AHORA - 300 }).impulsoCorte).toBeLessThan(
      con({ corte: AHORA - 100 }).impulsoCorte,
    );
  });

  it("lo apaga del todo pasado el plazo", () => {
    expect(con({ corte: AHORA - 5000 }).impulsoCorte).toBe(0);
  });

  it("ignora un corte que aún no ha pasado", () => {
    // Los relojes del servidor y del navegador no van sincronizados.
    expect(con({ corte: AHORA + 2000 }).impulsoCorte).toBeLessThanOrEqual(1);
  });
});
