import { getCurrentWindow } from "@tauri-apps/api/window";
import { useEffect, useRef, useState } from "react";

import type { FaceState, Senales } from "../lib/face";
import { VibiFace } from "./VibiFace";

type HatMoment = "falling" | "nervous" | "replacing" | "happy";

const IDLE_MS = 12_000;
const DOUBLE_TAP_MS = 280;
const MOMENT_MS: Record<HatMoment, number> = {
  falling: 520,
  nervous: 850,
  replacing: 680,
  happy: 1100,
};

export function CompanionPet({
  face,
  senales,
  resting,
  chatOpen,
  onOpenChat,
}: {
  face: FaceState;
  senales: Senales;
  resting: boolean;
  chatOpen: boolean;
  onOpenChat: () => void;
}) {
  const [idle, setIdle] = useState(false);
  const [held, setHeld] = useState(false);
  const [moment, setMoment] = useState<HatMoment | null>(null);
  const origin = useRef<{ x: number; y: number } | null>(null);
  const dragging = useRef(false);
  const dragTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTap = useRef(0);

  const touch = () => {
    setIdle(false);
    if (idleTimer.current) clearTimeout(idleTimer.current);
    if (resting && !moment) idleTimer.current = setTimeout(() => setIdle(true), IDLE_MS);
  };

  useEffect(() => {
    if (resting && !moment) {
      idleTimer.current = setTimeout(() => setIdle(true), IDLE_MS);
    } else {
      setIdle(false);
    }
    return () => {
      if (idleTimer.current) clearTimeout(idleTimer.current);
    };
  }, [resting, moment]);

  useEffect(() => {
    if (!moment) return;
    const next: Record<HatMoment, HatMoment | null> = {
      falling: "nervous",
      nervous: "replacing",
      replacing: "happy",
      happy: null,
    };
    const timer = setTimeout(() => setMoment(next[moment]), MOMENT_MS[moment]);
    return () => clearTimeout(timer);
  }, [moment]);

  useEffect(() => {
    if (!resting) setMoment(null);
  }, [resting]);

  useEffect(() => () => {
    if (dragTimer.current) clearTimeout(dragTimer.current);
    if (clickTimer.current) clearTimeout(clickTimer.current);
  }, []);

  const clearDrag = () => {
    if (dragTimer.current) clearTimeout(dragTimer.current);
    dragTimer.current = null;
    origin.current = null;
    setHeld(false);
  };

  const startDrag = () => {
    dragging.current = true;
    setHeld(true);
    void getCurrentWindow().startDragging().catch(() => undefined);
  };

  const expression = resting && (moment === "falling" || moment === "nervous")
    ? "recelo"
    : resting && moment === "happy"
      ? "pleased"
      : face;

  return (
    <div
      role="button"
      tabIndex={0}
      className="companion-face"
      data-tauri-drag-region
      data-pet-action={resting ? moment ?? (held ? "held" : idle ? "idle" : "rest") : "rest"}
      onPointerEnter={touch}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        touch();
        dragging.current = false;
        origin.current = { x: event.clientX, y: event.clientY };
        event.currentTarget.setPointerCapture?.(event.pointerId);
        if (dragTimer.current) clearTimeout(dragTimer.current);
        setHeld(resting);
        dragTimer.current = setTimeout(startDrag, 180);
      }}
      onPointerMove={(event) => {
        const start = origin.current;
        if (!start || dragging.current) return;
        if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < 4) return;
        clearDrag();
        startDrag();
      }}
      onPointerUp={(event) => {
        clearDrag();
        if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
      onPointerCancel={() => {
        clearDrag();
        dragging.current = false;
      }}
      onClick={() => {
        if (dragging.current) {
          dragging.current = false;
          return;
        }
        if (!resting || moment) {
          if (!moment) onOpenChat();
          return;
        }
        const now = Date.now();
        if (clickTimer.current && now - lastTap.current <= DOUBLE_TAP_MS) {
          clearTimeout(clickTimer.current);
          clickTimer.current = null;
          lastTap.current = 0;
          setMoment("falling");
          return;
        }
        lastTap.current = now;
        clickTimer.current = setTimeout(() => {
          clickTimer.current = null;
          onOpenChat();
        }, DOUBLE_TAP_MS);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpenChat();
        }
      }}
      aria-label="Preguntar a Vibi"
      aria-expanded={chatOpen}
      title="Pregúntame algo · doble toque para jugar"
    >
      <span className="companion-halo" aria-hidden="true">
        <span className="halo-nucleo" />
        <span className="halo-anillo" />
        <span className="halo-aura" />
      </span>
      <VibiFace state={expression} perfil="companion" senales={senales} />
    </div>
  );
}
