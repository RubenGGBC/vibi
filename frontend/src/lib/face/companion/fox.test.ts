import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadFoxSprites, type FoxSprites } from "../../foxSprites";
import { SENALES_QUIETAS } from "../modificadores";
import { callarOido, publicarNivelDeVoz } from "../oido";
import { createFoxScene } from "./fox";

vi.mock("../../foxSprites", () => ({
  FOX_WIDTH: 176,
  FOX_HEIGHT: 232,
  loadFoxSprites: vi.fn(),
}));

let scene: ReturnType<typeof createFoxScene>;
let host: HTMLSpanElement;
let preference: EventTarget & { matches: boolean };
const sprite = () => host.querySelector<HTMLElement>(".fox-agent")!;

beforeEach(() => {
  vi.useFakeTimers();
  preference = Object.assign(new EventTarget(), { matches: false });
  vi.stubGlobal("matchMedia", () => preference);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    clearRect: vi.fn(), drawImage: vi.fn(), imageSmoothingEnabled: false,
  } as unknown as CanvasRenderingContext2D);
  vi.mocked(loadFoxSprites).mockResolvedValue({
    animations: Array.from({ length: 3 }, () => Array.from({ length: 8 }, () => document.createElement("canvas"))),
    portrait: document.createElement("canvas"),
    actions: {
      internet: Array.from({ length: 8 }, () => document.createElement("canvas")),
      terminal: Array.from({ length: 8 }, () => document.createElement("canvas")),
      error: Array.from({ length: 8 }, () => document.createElement("canvas")),
    },
  });
  host = document.createElement("span");
});

afterEach(() => {
  scene?.dispose();
  callarOido();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function mount() {
  scene = createFoxScene(host);
  await Promise.resolve();
}

describe("el zorro del agente local", () => {
  it("espera entre parpadeos y solo se estira después de un reposo largo", async () => {
    await mount();
    expect(sprite().dataset.frame).toBe("0");
    expect(sprite().dataset.pose).toBe("original");
    vi.advanceTimersByTime(4200 + 90);
    expect(sprite().dataset.gesture).toBe("blink");
    expect(sprite().dataset.frame).toBe("1");
    expect(sprite().dataset.pose).toBe("animation");
    vi.advanceTimersByTime(7 * 90 + 7 * (4200 + 8 * 90));
    expect(sprite().dataset.gesture).toBe("stretch");
  });

  it("interrumpe el estiramiento al pensar y vuelve a reposo al acabar el gesto", async () => {
    await mount();
    scene.setState("logro");
    vi.advanceTimersByTime(3 * 170);
    expect(sprite().dataset.gesture).toBe("stretch");
    scene.setState("thinking");
    expect(sprite().dataset.gesture).toBe("touch");
    expect(sprite().dataset.frame).toBe("0");
    expect(sprite().dataset.pose).toBe("original");
    vi.advanceTimersByTime(8 * 150);
    expect(sprite().dataset.gesture).toBe("blink");
    expect(sprite().dataset.frame).toBe("0");
  });

  it("un trabajo largo no dispara los estiramientos de reposo", async () => {
    await mount();
    scene.setState("hacking");
    vi.advanceTimersByTime(60000);
    expect(sprite().dataset.gesture).toBe("terminal");
    expect(sprite().dataset.state).toBe("hacking");
    expect(sprite().dataset.pose).toBe("animation");
    expect(host.querySelector(".fox-agent-action")).not.toBeVisible();
  });

  it("cambia de Internet a Terminal y Error sin dejar temporizadores anteriores", async () => {
    await mount();
    scene.setState("searching");
    expect(sprite().dataset.gesture).toBe("internet");
    vi.advanceTimersByTime(4 * 180);
    expect(sprite().dataset.frame).toBe("4");
    scene.setState("hacking");
    expect(sprite().dataset.gesture).toBe("terminal");
    expect(sprite().dataset.frame).toBe("0");
    scene.setState("fallo");
    expect(sprite().dataset.gesture).toBe("error");
    vi.advanceTimersByTime(4 * 190 + 3 * 450);
    expect(sprite().dataset.frame).toBe("7");
    expect(sprite().dataset.pose).toBe("animation");
    vi.advanceTimersByTime(1100);
    expect(sprite().dataset.pose).toBe("original");
    scene.setState("idle");
    expect(sprite().dataset.pose).toBe("original");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("solo mantiene el globo mientras sigue buscando o navegando", async () => {
    await mount();
    scene.setState("browsing");
    vi.advanceTimersByTime(12000);
    expect(sprite().dataset.gesture).toBe("internet");
    expect(Number(sprite().dataset.frame)).toBeGreaterThanOrEqual(4);
    scene.setState("idle");
    expect(sprite().dataset.gesture).toBe("blink");
    expect(sprite().dataset.pose).toBe("original");
    vi.advanceTimersByTime(500);
    expect(sprite().dataset.pose).toBe("original");
  });

  it("se detiene sin conexión e interrumpe el gesto anterior", async () => {
    await mount();
    scene.setState("thinking");
    vi.advanceTimersByTime(300);
    scene.setState("offline");
    expect(sprite().dataset.pose).toBe("original");
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(60000);
    expect(sprite().dataset.state).toBe("offline");
    expect(sprite().dataset.pose).toBe("original");
  });

  it("recibe el micrófono y las señales reales sin reiniciar la animación", async () => {
    await mount();
    scene.setState("listening");
    publicarNivelDeVoz(.22);
    vi.advanceTimersByTime(80);
    expect(sprite().style.getPropertyValue("--fox-voice")).toBe("1");
    scene.setState("speaking");
    scene.setSenales({ ...SENALES_QUIETAS, cadencia: 20, pasos: 4, remoto: "Sobremesa", pendientes: 2 });
    expect(sprite().style.getPropertyValue("--fox-voice")).toBe("0.5");
    expect(sprite().title).toContain("Sobremesa");
    expect(sprite().title).toContain("4 pasos");
    expect(sprite().title).toContain("2 permisos");
    expect(sprite().dataset.remote).toBe("true");
  });

  it("respeta el movimiento reducido y reacciona si cambia la preferencia", async () => {
    preference.matches = true;
    await mount();
    scene.setState("thinking");
    expect(vi.getTimerCount()).toBe(0);
    expect(sprite().dataset.frame).toBe("0");
    preference.dispatchEvent(Object.assign(new Event("change"), { matches: false }));
    expect(sprite().dataset.gesture).toBe("touch");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("pausa la animación con la ventana oculta y retoma el estado vigente", async () => {
    await mount();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    document.dispatchEvent(new Event("visibilitychange"));
    scene.setState("thinking");
    expect(vi.getTimerCount()).toBe(0);
    hidden.mockReturnValue(false);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(sprite().dataset.gesture).toBe("touch");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("no resucita una escena desmontada cuando termina de cargar la imagen", async () => {
    let resolve!: (frames: FoxSprites) => void;
    vi.mocked(loadFoxSprites).mockReturnValue(new Promise((done) => { resolve = done; }));
    scene = createFoxScene(host);
    scene.dispose();
    resolve({ animations: [], portrait: document.createElement("canvas"), actions: { internet: [], terminal: [], error: [] } });
    await Promise.resolve();
    expect(host.children).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
  });
});
