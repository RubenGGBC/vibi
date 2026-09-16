import { beforeEach, describe, expect, it, vi } from "vitest";

const tauri = vi.hoisted(() => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-notification", () => tauri);

import { notificar } from "./notifications";

/** Fuera del companion, el plugin de Tauri revienta al importarse/llamarse. */
const sinTauri = () =>
  tauri.isPermissionGranted.mockRejectedValue(new Error("no hay Tauri"));

describe("notificar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Reflect.deleteProperty(globalThis, "Notification");
    Reflect.deleteProperty(globalThis, "navigator");
  });

  it("en el companion sale por el plugin de Tauri", async () => {
    tauri.isPermissionGranted.mockResolvedValue(true);
    await notificar("Vibi · Discord", "Jam pregunta algo");
    expect(tauri.sendNotification).toHaveBeenCalledWith({
      title: "Vibi · Discord",
      body: "Jam pregunta algo",
    });
  });

  it("en el navegador sale por la API del navegador", async () => {
    sinTauri();
    const construida: unknown[] = [];
    class FakeNotification {
      static permission = "granted";
      static requestPermission = vi.fn();
      constructor(titulo: string, opciones: unknown) {
        construida.push([titulo, opciones]);
      }
    }
    Object.assign(globalThis, { Notification: FakeNotification });

    await notificar("Vibi · WhatsApp", "Marcos ha escrito");
    expect(construida).toEqual([
      ["Vibi · WhatsApp", { body: "Marcos ha escrito" }],
    ]);
  });

  it("prefiere el service worker cuando lo hay", async () => {
    sinTauri();
    const showNotification = vi.fn();
    class FakeNotification {
      static permission = "granted";
      static requestPermission = vi.fn();
    }
    Object.assign(globalThis, {
      Notification: FakeNotification,
      navigator: {
        serviceWorker: {
          getRegistration: vi.fn().mockResolvedValue({ showNotification }),
        },
      },
    });

    await notificar("Vibi", "algo");
    expect(showNotification).toHaveBeenCalledWith("Vibi", { body: "algo" });
  });

  it("si el permiso está denegado se calla", async () => {
    sinTauri();
    class FakeNotification {
      static permission = "denied";
      static requestPermission = vi.fn();
      constructor() {
        throw new Error("no debería construirse");
      }
    }
    Object.assign(globalThis, { Notification: FakeNotification });
    await expect(notificar("Vibi", "algo")).resolves.toBeUndefined();
  });

  it("no avisa dos veces cuando en Tauri se deniega el permiso", async () => {
    tauri.isPermissionGranted.mockResolvedValue(false);
    tauri.requestPermission.mockResolvedValue("denied");
    class FakeNotification {
      static permission = "granted";
      static requestPermission = vi.fn();
      constructor() {
        throw new Error("el navegador no debe entrar si esto era Tauri");
      }
    }
    Object.assign(globalThis, { Notification: FakeNotification });

    await expect(notificar("Vibi", "algo")).resolves.toBeUndefined();
    expect(tauri.sendNotification).not.toHaveBeenCalled();
  });

  it("sin soporte de notificaciones no rompe nada", async () => {
    sinTauri();
    await expect(notificar("Vibi", "algo")).resolves.toBeUndefined();
  });
});
