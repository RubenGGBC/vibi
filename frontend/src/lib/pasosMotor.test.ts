import { describe, expect, it } from "vitest";

import { nombreLegible, resumirPaso } from "./pasosMotor";

/**
 * Cómo se lee un paso del motor en la ventana de proceso.
 *
 * El criterio: quien mira tiene que entender qué pasó sin saber cómo se llaman
 * las cosas por dentro. `CORTEX_STEP_TYPE_RUN_COMMAND` no le dice nada a nadie.
 */

describe("el nombre de un paso", () => {
  it("traduce los que salen a todas horas", () => {
    expect(nombreLegible("CORTEX_STEP_TYPE_RUN_COMMAND")).toBe("Terminal");
    expect(nombreLegible("CORTEX_STEP_TYPE_SEARCH_WEB")).toBe("Buscando");
    expect(nombreLegible("CORTEX_STEP_TYPE_VIEW_FILE")).toBe("Leyendo");
  });

  it("con lo que no conoce, al menos lo deja legible", () => {
    // `agy` estrena tipos sin avisar: mejor «Battle Mode» que el enum crudo.
    expect(nombreLegible("CORTEX_STEP_TYPE_BATTLE_MODE")).toBe("Battle mode");
  });

  it("no se atraganta con un tipo vacío", () => {
    expect(nombreLegible("")).toBe("Paso");
  });
});

describe("el detalle de un paso", () => {
  it("enseña el comando tal cual se lanzó", () => {
    const resumen = resumirPaso({
      turno: "t",
      tipo: "CORTEX_STEP_TYPE_RUN_COMMAND",
      estado: "CORTEX_STEP_STATUS_DONE",
      detalle: 'Start-Process explorer.exe "$HOME\\Downloads"',
      momento: 0,
    });

    expect(resumen).toContain("explorer.exe");
  });

  it("una consulta de búsqueda se entrecomilla, que es una frase", () => {
    const resumen = resumirPaso({
      turno: "t",
      tipo: "CORTEX_STEP_TYPE_SEARCH_WEB",
      estado: "CORTEX_STEP_STATUS_DONE",
      detalle: "cuanto pesa un gato",
      momento: 0,
    });

    expect(resumen).toBe("«cuanto pesa un gato»");
  });

  it("un comando de varias líneas se aplana", () => {
    // Un `Get-ChildItem` con tuberías llega con saltos y descuadra la lista.
    const resumen = resumirPaso({
      turno: "t",
      tipo: "CORTEX_STEP_TYPE_RUN_COMMAND",
      estado: "CORTEX_STEP_STATUS_DONE",
      detalle: "linea uno\nlinea dos\n  linea tres",
      momento: 0,
    });

    expect(resumen).not.toContain("\n");
    expect(resumen).toContain("linea uno");
  });
});
