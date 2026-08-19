import { describe, expect, it } from "vitest";

import { crearCadencia, decidirAnimo, retrasoVisible, senalesDe } from "./faceMood";
import { MAX_RETRASO } from "./face/modificadores";
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

describe("el retraso del canal que la cara llega a ver", () => {
  it("da el mismo valor mientras el cambio no se note", () => {
    // Se publicaba con precisión de milisegundo cinco veces por segundo, y
    // como el número siempre era distinto, React volvía a renderizar siempre.
    expect(retrasoVisible(1_000)).toBe(retrasoVisible(1_100));
  });

  it("satura donde la bola ya está apagada del todo", () => {
    // `ajustesDe` acota el retraso a MAX_RETRASO, así que por encima de ahí
    // todos los valores pintan lo mismo. El pong llega cada 30 s: sin saturar,
    // los 24 s que van de los 6 a los 30 renderizaban de balde.
    expect(retrasoVisible(30_000)).toBe(retrasoVisible(MAX_RETRASO));
  });

  it("sigue distinguiendo el desvanecido dentro de su rango", () => {
    expect(retrasoVisible(0)).toBeLessThan(retrasoVisible(3_000));
    expect(retrasoVisible(3_000)).toBeLessThan(retrasoVisible(MAX_RETRASO));
  });
});
