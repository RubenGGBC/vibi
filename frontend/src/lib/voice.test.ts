import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ACKNOWLEDGEMENTS,
  cleanSpeechText,
  createSpeechStream,
  prewarmAcknowledgements,
  takeAcknowledgement,
  takeSpeakableSentences,
} from "./voice";

const { apiBlob } = vi.hoisted(() => ({ apiBlob: vi.fn() }));
vi.mock("./api", () => ({ apiBlob }));

describe("takeSpeakableSentences", () => {
  it("no entrega nada mientras la frase sigue escribiéndose", () => {
    const { chunks, rest } = takeSpeakableSentences("Mañana en Bilbao hará");

    expect(chunks).toEqual([]);
    expect(rest).toBe("Mañana en Bilbao hará");
  });

  it("entrega la frase en cuanto se cierra y guarda lo que va suelto", () => {
    const { chunks, rest } = takeSpeakableSentences(
      "Mañana en Bilbao hará veinticuatro grados y estará despejado. Por la tarde",
    );

    expect(chunks).toEqual([
      "Mañana en Bilbao hará veinticuatro grados y estará despejado.",
    ]);
    expect(rest).toBe("Por la tarde");
  });

  it("agrupa frases demasiado cortas para no locutarlas sueltas", () => {
    // "Vale." suelto suena a corte; espera a tener material suficiente.
    const { chunks, rest } = takeSpeakableSentences("Vale. Ya.");

    expect(chunks).toEqual([]);
    expect(rest).toBe("Vale. Ya.");
  });

  it("con flush suelta lo que quede aunque no cierre con puntuación", () => {
    const { chunks, rest } = takeSpeakableSentences("Vale, ya está", {
      flush: true,
    });

    expect(chunks).toEqual(["Vale, ya está"]);
    expect(rest).toBe("");
  });

  it("no devuelve nada cuando solo queda espacio en blanco", () => {
    expect(takeSpeakableSentences("   ", { flush: true }).chunks).toEqual([]);
    expect(takeSpeakableSentences("").chunks).toEqual([]);
  });

  it("limpia el markdown que se cuele antes de locutar", () => {
    const { chunks } = takeSpeakableSentences(
      "- Hace **mucho** calor en toda la costa cantábrica hoy. ",
    );

    expect(chunks).toEqual(["Hace mucho calor en toda la costa cantábrica hoy."]);
  });

  it("parte una frase kilométrica para no pasarse del límite del backend", () => {
    const larga = `${"palabra ".repeat(120)}final.`;

    const { chunks } = takeSpeakableSentences(larga, { flush: true });

    expect(chunks.length).toBeGreaterThan(1);
    for (const chunk of chunks) expect(chunk.length).toBeLessThanOrEqual(600);
  });

  it("no repite texto ya entregado al encadenar llamadas", () => {
    // Simula el streaming: el buffer va creciendo y solo se consume lo cerrado.
    let buffer = "";
    const dichos: string[] = [];
    for (const delta of [
      "Mañana hará veinticuatro grados en Bilbao. ",
      "Por la tarde puede caer alguna gota suelta en la costa. ",
      "Nada serio",
    ]) {
      buffer += delta;
      const { chunks, rest } = takeSpeakableSentences(buffer);
      dichos.push(...chunks);
      buffer = rest;
    }
    const { chunks } = takeSpeakableSentences(buffer, { flush: true });
    dichos.push(...chunks);

    expect(dichos).toEqual([
      "Mañana hará veinticuatro grados en Bilbao.",
      "Por la tarde puede caer alguna gota suelta en la costa.",
      "Nada serio",
    ]);
  });

  it("arrastra una frase corta hasta juntarla con la siguiente", () => {
    // Bajo el mínimo no se emite suelta: se locuta con lo que venga detrás,
    // que suena mucho mejor que un audio de medio segundo.
    const primera = takeSpeakableSentences("Hace sol. ");
    expect(primera.chunks).toEqual([]);

    const segunda = takeSpeakableSentences(
      `${primera.rest}Y seguirá así durante todo el fin de semana. `,
    );
    expect(segunda.chunks).toEqual([
      "Hace sol. Y seguirá así durante todo el fin de semana.",
    ]);
  });
});

describe("createSpeechStream", () => {
  let reproducidos: string[];

  /** Deja que se resuelvan las promesas de la cola. */
  const asentar = async () => {
    for (let i = 0; i < 12; i += 1) await Promise.resolve();
  };

  beforeEach(() => {
    reproducidos = [];
    apiBlob.mockReset();
    // Cada petición devuelve un blob que "recuerda" el texto que la originó.
    apiBlob.mockImplementation((_url: string, init: { body: string }) => {
      const { texto } = JSON.parse(init.body) as { texto: string };
      return Promise.resolve(new Blob([texto], { type: "audio/mpeg" }));
    });
    vi.stubGlobal("URL", {
      createObjectURL: (blob: Blob) => `blob:${(blob as Blob & { _t?: string })._t ?? ""}`,
      revokeObjectURL: () => undefined,
    });
    // Un Audio que termina en cuanto empieza y anota lo que le tocaba sonar.
    vi.stubGlobal(
      "Audio",
      class {
        private handlers: Record<string, (() => void)[]> = {};
        constructor(public src: string) {}
        addEventListener(name: string, handler: () => void) {
          (this.handlers[name] ??= []).push(handler);
        }
        play() {
          reproducidos.push(this.src);
          queueMicrotask(() => this.handlers.ended?.forEach((h) => h()));
          return Promise.resolve();
        }
        pause() {}
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("pide la síntesis de una frase sin esperar al resto de la respuesta", async () => {
    const stream = createSpeechStream(() => undefined);

    stream.push("Mañana hará veinticuatro grados en Bilbao. Por la");
    await asentar();

    expect(apiBlob).toHaveBeenCalledTimes(1);
    expect(JSON.parse(apiBlob.mock.calls[0][1].body).texto).toBe(
      "Mañana hará veinticuatro grados en Bilbao.",
    );
    stream.cancel();
  });

  it("locuta en orden y avisa al terminar", async () => {
    const onEnd = vi.fn();
    const stream = createSpeechStream(onEnd);

    stream.push("Mañana hará veinticuatro grados en Bilbao. ");
    await asentar();
    stream.push(
      "Mañana hará veinticuatro grados en Bilbao. Por la tarde puede caer alguna gota suelta. ",
    );
    await asentar();
    stream.end();
    await asentar();

    expect(reproducidos).toEqual([
      "blob:",
      "blob:",
    ]);
    expect(apiBlob).toHaveBeenCalledTimes(2);
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("no locuta dos veces el texto que ya ha consumido", async () => {
    const stream = createSpeechStream(() => undefined);

    // El evento manda el acumulado completo en cada delta.
    stream.push("Hace sol y hará bueno todo el fin de semana largo. ");
    await asentar();
    stream.push(
      "Hace sol y hará bueno todo el fin de semana largo. Aprovecha para salir un rato. ",
    );
    await asentar();
    stream.end();
    await asentar();

    const dichos = apiBlob.mock.calls.map(
      (call) => JSON.parse(call[1].body).texto,
    );
    expect(dichos).toEqual([
      "Hace sol y hará bueno todo el fin de semana largo.",
      "Aprovecha para salir un rato.",
    ]);
  });

  it("no repite la respuesta cuando el cierre del turno llega recortado", async () => {
    const stream = createSpeechStream(() => undefined);

    // Los deltas dejan un espacio final que el backend quita al cerrar.
    stream.push("Hace sol y hará bueno todo el fin de semana largo. ");
    await asentar();
    stream.push("Hace sol y hará bueno todo el fin de semana largo.");
    stream.end();
    await asentar();

    const dichos = apiBlob.mock.calls.map(
      (call) => JSON.parse(call[1].body).texto,
    );
    expect(dichos).toEqual(["Hace sol y hará bueno todo el fin de semana largo."]);
  });

  it("locuta la respuesta completa si los eventos nunca llegaron", async () => {
    const onEnd = vi.fn();
    const stream = createSpeechStream(onEnd);

    // Sin WebSocket no hubo ni un solo push intermedio.
    stream.push("Hace sol y seguirá así todo el fin de semana.");
    stream.end();
    await asentar();

    const dichos = apiBlob.mock.calls.map(
      (call) => JSON.parse(call[1].body).texto,
    );
    expect(dichos).toEqual(["Hace sol y seguirá así todo el fin de semana."]);
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("añade solo la cola que se perdió si el cierre trae más texto", async () => {
    const stream = createSpeechStream(() => undefined);

    stream.push("Hace sol y hará bueno todo el fin de semana largo. ");
    await asentar();
    stream.push(
      "Hace sol y hará bueno todo el fin de semana largo. Aprovecha para salir.",
    );
    stream.end();
    await asentar();

    const dichos = apiBlob.mock.calls.map(
      (call) => JSON.parse(call[1].body).texto,
    );
    expect(dichos).toEqual([
      "Hace sol y hará bueno todo el fin de semana largo.",
      "Aprovecha para salir.",
    ]);
  });

  it("termina aunque el turno no haya dicho nada", async () => {
    const onEnd = vi.fn();
    const stream = createSpeechStream(onEnd);

    stream.end();
    await asentar();

    expect(onEnd).toHaveBeenCalledTimes(1);
    expect(apiBlob).not.toHaveBeenCalled();
  });

  it("al cancelar deja de locutar y no vuelve a llamar a onEnd", async () => {
    const onEnd = vi.fn();
    const stream = createSpeechStream(onEnd);

    stream.push("Una frase lo bastante larga como para salir por el altavoz. ");
    stream.cancel();
    await asentar();
    stream.push("Otra frase que ya no debería sintetizarse nunca jamás. ");
    stream.end();
    await asentar();

    expect(onEnd).not.toHaveBeenCalled();
    expect(apiBlob).toHaveBeenCalledTimes(1);
  });
});

describe("muletillas", () => {
  const asentar = async () => {
    for (let i = 0; i < 12; i += 1) await Promise.resolve();
  };

  // El caché de muletillas vive en el módulo: sin recargarlo, un test
  // arrastraría los blobs del anterior.
  const cargarVoice = async () => {
    vi.resetModules();
    return import("./voice");
  };

  beforeEach(() => {
    apiBlob.mockReset();
    apiBlob.mockImplementation((_url: string, init: { body: string }) => {
      const { texto } = JSON.parse(init.body) as { texto: string };
      return Promise.resolve(new Blob([texto], { type: "audio/mpeg" }));
    });
  });

  it("son cortas: una larga alargaría justo lo que quiere disimular", () => {
    for (const frase of ACKNOWLEDGEMENTS) {
      expect(frase.length).toBeLessThanOrEqual(24);
    }
  });

  it("no hay muletilla disponible mientras no se hayan pre-sintetizado", async () => {
    const voice = await cargarVoice();

    expect(voice.takeAcknowledgement()).toBeNull();
  });

  it("las deja listas en memoria para que suenen al instante", async () => {
    const voice = await cargarVoice();

    await voice.prewarmAcknowledgements();

    expect(apiBlob).toHaveBeenCalledTimes(ACKNOWLEDGEMENTS.length);
    expect(voice.takeAcknowledgement()).toBeInstanceOf(Blob);
  });

  it("no las vuelve a pedir si ya están calientes", async () => {
    const voice = await cargarVoice();
    await voice.prewarmAcknowledgements();
    apiBlob.mockClear();

    await voice.prewarmAcknowledgements();

    expect(apiBlob).not.toHaveBeenCalled();
  });

  it("aguanta que el TTS falle: sin muletilla, pero sin romper nada", async () => {
    const voice = await cargarVoice();
    apiBlob.mockRejectedValue(new Error("502"));

    await expect(voice.prewarmAcknowledgements()).resolves.toBeUndefined();
    expect(voice.takeAcknowledgement()).toBeNull();
  });

  it("suena antes que la respuesta y sin solaparse con ella", async () => {
    const reproducidos: string[] = [];
    vi.stubGlobal("URL", {
      createObjectURL: () => "blob:x",
      revokeObjectURL: () => undefined,
    });
    const sonando: (() => void)[] = [];
    vi.stubGlobal(
      "Audio",
      class {
        private handlers: Record<string, (() => void)[]> = {};
        constructor(public src: string) {}
        addEventListener(name: string, handler: () => void) {
          (this.handlers[name] ??= []).push(handler);
        }
        play() {
          reproducidos.push("audio");
          // No termina solo: así se comprueba que la cola espera de verdad.
          sonando.push(() => this.handlers.ended?.forEach((h) => h()));
          return Promise.resolve();
        }
        pause() {}
      },
    );

    const ack = new Blob(["Vale."], { type: "audio/mpeg" });
    const stream = createSpeechStream(() => undefined, { acknowledgement: ack });
    stream.push("Mañana hará veinticuatro grados y estará despejado del todo. ");
    await asentar();

    // Solo suena la muletilla; la respuesta espera su turno en la cola.
    expect(reproducidos).toHaveLength(1);

    sonando.shift()?.();
    await asentar();
    expect(reproducidos).toHaveLength(2);

    stream.cancel();
    vi.unstubAllGlobals();
  });
});

describe("cleanSpeechText", () => {
  it("sigue quitando enlaces, código y viñetas", () => {
    expect(
      cleanSpeechText("- Mira [la web](https://ejemplo.com) y `npm run dev`"),
    ).toBe("Mira la web y npm run dev");
  });
});
