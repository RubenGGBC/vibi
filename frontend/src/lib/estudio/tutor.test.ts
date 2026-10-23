import { describe, expect, it } from "vitest";

import type { Escena, Pregunta } from "./tipos";
import { estadoPregunta, mensajeNoLoEntiendo, mensajeTrasFallar } from "./tutor";

const pregunta: Pregunta = {
  enunciado: "¿Cambia el periodo?",
  opciones: ["Se duplica", "Se reduce", "No cambia"],
  correcta: 2,
  explicacion: "Solo depende de la longitud",
  pistas: ["Mueve la masa"],
};

describe("estadoPregunta", () => {
  it("un fallo destapa la pista, el siguiente la explicación", () => {
    expect(estadoPregunta(pregunta, [])).toMatchObject({ resuelta: false, pista: null });
    expect(estadoPregunta(pregunta, [0])).toMatchObject({ resuelta: false, pista: "Mueve la masa", explicacion: null });
    expect(estadoPregunta(pregunta, [0, 1])).toMatchObject({
      resuelta: true,
      acertada: false,
      pista: null,
      explicacion: "Solo depende de la longitud",
    });
  });

  it("acertar tras una pista la cierra", () => {
    expect(estadoPregunta(pregunta, [0, 2])).toMatchObject({ resuelta: true, acertada: true, fallos: 1 });
  });

  it("sin pistas, el primer fallo ya enseña la explicación", () => {
    expect(estadoPregunta({ ...pregunta, pistas: undefined }, [1]).resuelta).toBe(true);
  });
});

describe("mensajes al tutor", () => {
  const escena = {
    pasos: [
      { texto: "Mira", idea: "La masa no cuenta", mostrar: [], ocultar: [], resaltar: [], pregunta },
    ],
    progreso: { visto_hasta: 0, respuestas: { "1": [0, 1] } },
  } as unknown as Escena;

  it("dicen el paso y de qué va", () => {
    expect(mensajeNoLoEntiendo(escena, 0)).toBe(
      "(Estudio, paso 1) No lo entiendo: «La masa no cuenta». ¿Me lo explicas de otra forma?",
    );
    expect(mensajeTrasFallar(escena, 0)).toContain("elegí «Se duplica» y luego «Se reduce»");
  });
});

describe("voz del tutor", () => {
  it("narra lo que cuenta, lo que te toca y la pregunta", async () => {
    const { narracionDePaso } = await import("./vozTutor");
    expect(
      narracionDePaso({
        texto: "Mira la bola roja.",
        tarea: "Sube la masa.",
        mostrar: [],
        ocultar: [],
        resaltar: [],
        pregunta,
      }),
    ).toBe("Mira la bola roja. Sube la masa. ¿Cambia el periodo?");
  });

});
