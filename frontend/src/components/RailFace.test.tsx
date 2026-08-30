import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SENALES_QUIETAS } from "../lib/face";
import { RailFace } from "./RailFace";

vi.mock("../lib/faceMood", () => ({
  useFaceMood: () => ({
    cara: "idle",
    copy: "",
    senales: SENALES_QUIETAS,
  }),
}));

class ResizeObserverStub {
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

describe("RailFace", () => {
  it("usa el mismo rig vectorial que el companion local", () => {
    const { container } = render(<RailFace />);

    expect(container.querySelector(".rail-cara .face-canvas-companion")).not.toBeNull();
    expect(container.querySelector(".companion-vibi-svg")).not.toBeNull();
  });
});
