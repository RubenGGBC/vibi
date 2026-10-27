import { invoke } from "@tauri-apps/api/core";
import { fireEvent, render, screen, act } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SENALES_QUIETAS } from "../lib/face/modificadores";
import { NotchCompanion } from "./NotchCompanion";
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn().mockRejectedValue(new Error("preview")) }));
vi.mock("./FoxVibi", () => ({ FoxVibi: () => null }));
vi.mock("./MascotaChat", () => ({ MascotaChat: () => <input aria-label="Borrador" /> }));
afterEach(() => vi.useRealTimers());
it("despliega al acercar el ratón y espera antes de ocultarse", () => {
  vi.useFakeTimers();
  const onExpand = vi.fn();
  const { container } = render(<NotchCompanion state="idle" senales={SENALES_QUIETAS} copy="En espera" expanded={false} onExpand={onExpand} voiceActive={false} onVoice={vi.fn()} onEndVoice={vi.fn()} onIniciarSesion={vi.fn()} />);
  const panel = container.querySelector("main")!;
  fireEvent.pointerEnter(panel);
  expect(onExpand).toHaveBeenCalledWith(true);
  onExpand.mockClear();
  fireEvent.pointerLeave(panel);
  act(() => vi.advanceTimersByTime(600));
  expect(onExpand).not.toHaveBeenCalled();
  fireEvent.pointerEnter(panel);
  onExpand.mockClear();
  act(() => vi.advanceTimersByTime(100));
  expect(onExpand).not.toHaveBeenCalled();
  fireEvent.pointerLeave(panel);
  act(() => vi.advanceTimersByTime(650));
  expect(onExpand).toHaveBeenCalledWith(false);
});
it("conserva el borrador al ocultarse y volver a abrirse", () => {
  const props = { state: "idle" as const, senales:SENALES_QUIETAS, copy:"En espera", onExpand:vi.fn(), voiceActive:false, onVoice:vi.fn(), onEndVoice:vi.fn(), onIniciarSesion:vi.fn() };
  const { rerender } = render(<NotchCompanion {...props} expanded />);
  fireEvent.change(screen.getByLabelText("Borrador"), { target: { value:"Mi pregunta" } });
  rerender(<NotchCompanion {...props} expanded={false} />);
  rerender(<NotchCompanion {...props} expanded />);
  expect(screen.getByLabelText("Borrador")).toHaveValue("Mi pregunta");
});

it("detecta proximidad nativa sin recibir eventos del ratón en la webview", async () => {
  vi.useFakeTimers();
  vi.mocked(invoke).mockResolvedValueOnce(true);
  const onExpand = vi.fn();
  render(<NotchCompanion state="idle" senales={SENALES_QUIETAS} copy="En espera" expanded={false} onExpand={onExpand} voiceActive={false} onVoice={vi.fn()} onEndVoice={vi.fn()} onIniciarSesion={vi.fn()} />);
  await act(async () => { await Promise.resolve(); });
  expect(invoke).toHaveBeenCalledWith("notch_pointer_near", { expanded:false });
  expect(onExpand).toHaveBeenCalledWith(true);
});
it("no se pliega mientras se escribe aunque el ratón salga", () => {
  vi.useFakeTimers();
  const onExpand = vi.fn();
  const { container } = render(<NotchCompanion state="idle" senales={SENALES_QUIETAS} copy="En espera" expanded onExpand={onExpand} voiceActive={false} onVoice={vi.fn()} onEndVoice={vi.fn()} onIniciarSesion={vi.fn()} />);
  fireEvent.focus(screen.getByLabelText("Borrador"));
  fireEvent.pointerLeave(container.querySelector("main")!);
  act(() => vi.advanceTimersByTime(1000));
  expect(onExpand).not.toHaveBeenCalledWith(false);
});
