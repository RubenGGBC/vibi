import { afterEach, describe, expect, it } from "vitest";

import { baseDeLaApi, corriendoEnLaApp } from "./entorno";

/**
 * Dónde cree la interfaz que vive.
 *
 * Importa más de lo que parece: servida por el core, le bastan rutas
 * relativas. Dentro de la ventana de escritorio el origen es `tauri://` y esas
 * mismas rutas no llevan a ninguna parte, así que la ventana se abría negra y
 * sin un solo error visible.
 */

const conProtocolo = (protocol: string, hostname = "localhost") => {
  Object.defineProperty(window, "location", {
    value: { protocol, hostname, origin: `${protocol}//${hostname}` },
    writable: true,
    configurable: true,
  });
};

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
});

describe("saber si esto es la aplicación de escritorio", () => {
  it("lo reconoce por el puente que Tauri inyecta", () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};

    expect(corriendoEnLaApp()).toBe(true);
  });

  it("lo reconoce también por el protocolo, que es lo que llega primero", () => {
    // El puente aparece pronto, pero no necesariamente antes de que este
    // módulo se evalúe. El protocolo sí está desde el principio.
    conProtocolo("tauri:");

    expect(corriendoEnLaApp()).toBe(true);
  });

  it("en el navegador de siempre dice que no", () => {
    conProtocolo("http:", "127.0.0.1");

    expect(corriendoEnLaApp()).toBe(false);
  });
});

describe("a dónde manda las peticiones", () => {
  it("servida por el core, se queda con rutas relativas", () => {
    conProtocolo("http:", "127.0.0.1");

    expect(baseDeLaApi()).toBe("");
  });

  it("en la aplicación apunta al core de esta máquina", () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};

    expect(baseDeLaApi()).toBe("http://127.0.0.1:8000");
  });
});
