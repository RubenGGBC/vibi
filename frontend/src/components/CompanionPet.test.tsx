import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SENALES_QUIETAS } from "../lib/face";
import { CompanionPet } from "./CompanionPet";

const startDragging = vi.fn(async () => undefined);
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ startDragging }),
}));
vi.mock("./VibiFace", () => ({ VibiFace: () => null }));

const mount = (onOpenChat = vi.fn()) => {
  render(
    <CompanionPet
      face="idle"
      senales={SENALES_QUIETAS}
      resting
      chatOpen={false}
      onOpenChat={onOpenChat}
    />,
  );
  return { face: screen.getByRole("button", { name: "Preguntar a Vibi" }), onOpenChat };
};

beforeEach(() => {
  vi.useFakeTimers();
  startDragging.mockClear();
});
afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
});

it("abre el chat con un toque aislado sin interpretar un doble toque", () => {
  const { face, onOpenChat } = mount();

  fireEvent.click(face);
  expect(onOpenChat).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(280));

  expect(onOpenChat).toHaveBeenCalledOnce();
  expect(face).toHaveAttribute("data-pet-action", "rest");
});

it("deja caer el sombrero y pasa de nerviosa a contenta con dos toques", () => {
  const { face, onOpenChat } = mount();

  fireEvent.click(face);
  act(() => vi.advanceTimersByTime(90));
  fireEvent.click(face);

  expect(face).toHaveAttribute("data-pet-action", "falling");
  act(() => vi.advanceTimersByTime(520));
  expect(face).toHaveAttribute("data-pet-action", "nervous");
  act(() => vi.advanceTimersByTime(850));
  expect(face).toHaveAttribute("data-pet-action", "replacing");
  act(() => vi.advanceTimersByTime(680));
  expect(face).toHaveAttribute("data-pet-action", "happy");
  act(() => vi.advanceTimersByTime(1100));
  expect(face).toHaveAttribute("data-pet-action", "rest");
  expect(onOpenChat).not.toHaveBeenCalled();
});

it("se adormece sin contacto y despierta al volver a tocarla", () => {
  const { face } = mount();

  act(() => vi.advanceTimersByTime(12_000));
  expect(face).toHaveAttribute("data-pet-action", "idle");
  fireEvent.pointerEnter(face);

  expect(face).toHaveAttribute("data-pet-action", "rest");
});

it("responde al agarre y arrastra sin abrir el chat", () => {
  const { face, onOpenChat } = mount();

  fireEvent.pointerDown(face, { button: 0, clientX: 10, clientY: 10, pointerId: 1 });
  expect(face).toHaveAttribute("data-pet-action", "held");
  fireEvent.pointerMove(face, { clientX: 22, clientY: 10, pointerId: 1 });
  fireEvent.pointerUp(face, { pointerId: 1 });
  fireEvent.click(face);

  expect(startDragging).toHaveBeenCalledOnce();
  expect(onOpenChat).not.toHaveBeenCalled();
});
