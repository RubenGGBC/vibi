import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SENALES_QUIETAS } from "../lib/face";
import { VibiFace } from "./VibiFace";

const mocks = vi.hoisted(() => ({ crearEscenaCara: vi.fn() }));

// La escena de verdad tiene su propia batería en `lib/face/escena.test.ts`.
// Aquí lo que se prueba es el cableado: que se monte una vez y que le llegue
// todo lo que cambia.
vi.mock("../lib/face", async (importarReal) => ({
  ...(await importarReal<typeof import("../lib/face")>()),
  crearEscenaCara: mocks.crearEscenaCara,
}));

// jsdom no implementa ResizeObserver y la cara lo usa para reajustarse.
class ResizeObserverStub {
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const escenaFalsa = () => ({
  setState: vi.fn(),
  setSenales: vi.fn(),
  setPointer: vi.fn(),
  clearPointer: vi.fn(),
  dibujar: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
});

beforeEach(() => {
  mocks.crearEscenaCara.mockReset();
});

describe("VibiFace", () => {
  it("deja el contenedor en su sitio", () => {
    mocks.crearEscenaCara.mockReturnValue(escenaFalsa());

    const { container, unmount } = render(<VibiFace state="idle" />);

    expect(container.querySelector(".face-canvas")).not.toBeNull();
    expect(() => unmount()).not.toThrow();
  });

  it("monta la escena una sola vez y le pasa cada cambio de estado", () => {
    const scene = escenaFalsa();
    mocks.crearEscenaCara.mockReturnValue(scene);

    const { rerender, unmount } = render(<VibiFace state="idle" />);
    expect(mocks.crearEscenaCara).toHaveBeenCalledTimes(1);
    expect(scene.setState).toHaveBeenLastCalledWith("idle");

    rerender(<VibiFace state="listening" />);
    rerender(<VibiFace state="hacking" />);

    // Cambiar de estado no puede reconstruir la escena: se perdería el morph.
    expect(mocks.crearEscenaCara).toHaveBeenCalledTimes(1);
    expect(scene.setState).toHaveBeenLastCalledWith("hacking");

    unmount();
    expect(scene.dispose).toHaveBeenCalledTimes(1);
  });

  it("le reenvía las señales vivas del turno", () => {
    const scene = escenaFalsa();
    mocks.crearEscenaCara.mockReturnValue(scene);

    const { rerender } = render(<VibiFace state="thinking" />);
    const senales = { ...SENALES_QUIETAS, pasos: 7, cadencia: 22 };
    rerender(<VibiFace state="thinking" senales={senales} />);

    expect(scene.setSenales).toHaveBeenLastCalledWith(senales);
  });
});
