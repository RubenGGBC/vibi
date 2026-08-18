import { describe, expect, it } from "vitest";

import { crearCadencia, decidirAnimo, senalesDe } from "./faceMood";
import type { ChatRuntimeState } from "../types";

const ENTRADA = {
  voz: "idle" as const,
  enConversacion: false,
  canal: "conectado" as const,
  pendientes: 0,
  fase: null,
  herramienta: "",
  destello: null,
  ahora: 1000,
};

const runtime = (extra: Partial<ChatRuntimeState> = {}): ChatRuntimeState => ({
  conversation_id: "c",
  turn_id: "t",
  label: "",
  text: "",
  boundaries: 0,
  fase: "arranque",
  herramienta: "",
  ...extra,
});

describe("qué cara toca", () => {
  it("pone cara de arrancar mientras el motor despierta", () => {
    // Antes esta fase no tenía cara y el turno empezaba con la de pensar,
    // aunque todavía no estuviera pensando nada.
    expect(decidirAnimo({ ...ENTRADA, fase: "arranque" }).cara).toBe("arranque");
  });

  it("deja el arranque en cuanto empieza a usar algo", () => {
    expect(
      decidirAnimo({ ...ENTRADA, fase: "herramienta", herramienta: "Bash" }).cara,
    ).toBe("hacking");
  });

  it("no cuenta nada más cuando no hay servidor", () => {
    // Con el canal caído, lo que sabemos del turno se quedó congelado en el
    // último evento: cualquier otra cara sería mentira.
    expect(
      decidirAnimo({
        ...ENTRADA,
        canal: "caido",
        fase: "herramienta",
        herramienta: "Bash",
      }).cara,
    ).toBe("offline");
  });

  it("da prioridad a hablar contigo por encima del arranque", () => {
    expect(
      decidirAnimo({
        ...ENTRADA,
        voz: "listening",
        enConversacion: true,
        fase: "arranque",
      }).cara,
    ).toBe("listening");
  });
});

describe("recoger las señales del turno", () => {
  it("saca los pasos encadenados de boundaries", () => {
    expect(senalesDe({ runtime: runtime({ boundaries: 7 }) }).pasos).toBe(7);
  });

  it("no marca nada como remoto cuando el trabajo es de casa", () => {
    expect(senalesDe({ runtime: runtime({ herramienta: "Bash" }) }).remoto).toBeNull();
  });

  it("marca como remoto lo que corre en la malla", () => {
    expect(senalesDe({ runtime: runtime({ herramienta: "pc_shell_run" }) }).remoto).not.toBeNull();
    expect(senalesDe({ runtime: runtime({ herramienta: "devices_list" }) }).remoto).not.toBeNull();
  });

  it("aguanta que no haya turno en marcha", () => {
    const senales = senalesDe({ runtime: null });
    expect(senales.pasos).toBe(0);
    expect(senales.remoto).toBeNull();
  });

  it("arrastra los permisos pendientes", () => {
    expect(senalesDe({ runtime: null, pendientes: 4 }).pendientes).toBe(4);
  });
});

describe("medir el caudal de tokens", () => {
  it("cuenta lo que ha llegado en la ventana", () => {
    const cadencia = crearCadencia(1);
    for (let i = 0; i < 20; i += 1) cadencia.anotar(i * 0.05);
    expect(cadencia.porSegundo(1)).toBeGreaterThan(15);
  });

  it("se olvida de lo viejo", () => {
    // Si el modelo se atasca, la cadencia tiene que caer a cero: esa quietud es
    // la información.
    const cadencia = crearCadencia(1);
    for (let i = 0; i < 20; i += 1) cadencia.anotar(i * 0.05);
    expect(cadencia.porSegundo(30)).toBe(0);
  });

  it("empieza a cero", () => {
    expect(crearCadencia(1).porSegundo(5)).toBe(0);
  });
});
