import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VibiFace } from "./VibiFace";

const mocks = vi.hoisted(() => ({ createFaceScene: vi.fn() }));

vi.mock("../lib/face3d", () => ({
  createFaceScene: mocks.createFaceScene,
  supportsWebGL: () => false,
}));

// jsdom no implementa ResizeObserver y la cara la usa para reajustar el lienzo.
class ResizeObserverStub {
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

beforeEach(() => {
  mocks.createFaceScene.mockReset();
});

describe("VibiFace", () => {
  it("renderiza el contenedor sin romperse cuando no hay escena disponible", () => {
    mocks.createFaceScene.mockReturnValue(null);

    const { container, unmount } = render(<VibiFace state="idle" />);

    expect(container.querySelector(".face-canvas")).not.toBeNull();
    expect(() => unmount()).not.toThrow();
  });

  it("monta la escena una sola vez y le pasa cada cambio de estado", () => {
    const scene = { setState: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
    mocks.createFaceScene.mockReturnValue(scene);

    const { rerender, unmount } = render(<VibiFace state="idle" />);
    expect(mocks.createFaceScene).toHaveBeenCalledTimes(1);
    expect(scene.setState).toHaveBeenLastCalledWith("idle");

    rerender(<VibiFace state="listening" />);
    rerender(<VibiFace state="speaking" />);

    // cambiar de estado no debe reconstruir la escena
    expect(mocks.createFaceScene).toHaveBeenCalledTimes(1);
    expect(scene.setState).toHaveBeenLastCalledWith("speaking");

    unmount();
    expect(scene.dispose).toHaveBeenCalledTimes(1);
  });
});
