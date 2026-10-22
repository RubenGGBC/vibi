import { FOX_HEIGHT, FOX_WIDTH, loadFoxSprites, type FoxAction, type FoxSprites } from "../../foxSprites";
import type { FaceScene } from "../escena";
import type { FaceState } from "../estados";
import { SENALES_QUIETAS, type Senales } from "../modificadores";
import { nivelDeVoz } from "../oido";

type AmbientGesture = "blink" | "stretch" | "touch";
type Gesture = AmbientGesture | FoxAction;
const ROW: Record<AmbientGesture, number> = { blink: 0, stretch: 1, touch: 2 };
const FRAME_MS: Record<Gesture, number> = { blink: 90, stretch: 170, touch: 150, internet: 180, terminal: 170, error: 190 };
const isAction = (value: Gesture): value is FoxAction => value === "internet" || value === "terminal" || value === "error";

// Each badge describes the real state, even when several states share one of
// the supplied animations. Tool names and feedback still come from mood.
const ACTIONS: Record<FaceState, { mark: string; label: string; gesture: Gesture }> = {
  idle: { mark: "", label: "En reposo", gesture: "blink" },
  listening: { mark: "◉", label: "Te escucho", gesture: "blink" },
  thinking: { mark: "?", label: "Pensando", gesture: "touch" },
  speaking: { mark: "≋", label: "Hablando", gesture: "blink" },
  arranque: { mark: "…", label: "Arrancando el turno", gesture: "touch" },
  vigilando: { mark: "◷", label: "Pendiente de tu encargo", gesture: "blink" },
  working: { mark: "⚙", label: "Trabajando", gesture: "blink" },
  searching: { mark: "⌕", label: "Buscando en internet", gesture: "internet" },
  browsing: { mark: "◎", label: "Navegando", gesture: "internet" },
  rummaging: { mark: "⌕", label: "Buscando archivos", gesture: "touch" },
  reading: { mark: "≡", label: "Leyendo", gesture: "touch" },
  writing: { mark: "✎", label: "Escribiendo", gesture: "blink" },
  noting: { mark: "✎", label: "Tomando nota", gesture: "blink" },
  hacking: { mark: ">_", label: "En el terminal", gesture: "terminal" },
  peeking: { mark: "◉", label: "Mirando tu pantalla", gesture: "blink" },
  handling: { mark: "↖", label: "Manejando tu pantalla", gesture: "blink" },
  launching: { mark: "↗", label: "Abriendo una aplicación", gesture: "blink" },
  sending: { mark: "↥", label: "Moviendo un archivo", gesture: "blink" },
  reaching: { mark: "⇄", label: "Hablando con tu equipo", gesture: "blink" },
  vibing: { mark: "♪", label: "Poniendo música", gesture: "blink" },
  forjando: { mark: "⚒", label: "Forjando una herramienta", gesture: "touch" },
  trastienda: { mark: "⚙", label: "En la trastienda", gesture: "blink" },
  waiting: { mark: "?", label: "Esperando tu permiso", gesture: "touch" },
  recelo: { mark: "!", label: "Una orden necesita tu atención", gesture: "touch" },
  denegada: { mark: "−", label: "Orden descartada", gesture: "touch" },
  alert: { mark: "!", label: "Necesito atención", gesture: "error" },
  fallo: { mark: "!", label: "Ha fallado una tarea", gesture: "error" },
  perdida: { mark: "!", label: "Conexión perdida durante el turno", gesture: "blink" },
  pleased: { mark: "✓", label: "Hecho", gesture: "stretch" },
  logro: { mark: "✓", label: "Tarea terminada", gesture: "stretch" },
  vinculando: { mark: "+", label: "Vinculando este equipo", gesture: "blink" },
  cambiando: { mark: "↔", label: "Cambiando de tamaño", gesture: "blink" },
  offline: { mark: "×", label: "Sin conexión con el servidor", gesture: "blink" },
};

/** A sprite scene with the same live inputs as the original companion rig. */
export function createFoxScene(container: HTMLElement): FaceScene {
  const root = document.createElement("span");
  root.className = "fox-agent";
  const canvas = document.createElement("canvas");
  canvas.className = "fox-agent-sprite";
  canvas.width = FOX_WIDTH;
  canvas.height = FOX_HEIGHT;
  const context = canvas.getContext("2d");
  const badge = document.createElement("span");
  badge.className = "fox-agent-action";
  root.append(canvas, badge);
  container.append(root);

  let alive = true;
  let state: FaceState = "idle";
  let signals: Senales = SENALES_QUIETAS;
  let sprites: FoxSprites | undefined;
  let resting = true;
  let gesture: Gesture = "blink";
  let frame = 0;
  let idleBlinks = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let voiceTimer: ReturnType<typeof setInterval> | undefined;
  const preference = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  let reduced = preference?.matches ?? false;

  const draw = () => {
    root.dataset.state = state;
    root.dataset.gesture = gesture;
    root.dataset.frame = String(frame);
    const original = resting || frame === 0 || (!isAction(gesture) && frame === 7);
    root.dataset.pose = original ? "original" : "animation";
    badge.hidden = !ACTIONS[state].mark || (isAction(gesture) && !resting && frame >= 3);
    if (!context || !sprites) return;
    context.clearRect(0, 0, FOX_WIDTH, FOX_HEIGHT);
    context.imageSmoothingEnabled = false;
    if (original) {
      // The standalone artwork is the canonical Vibi, not frame 1 of the
      // animation sheet. Keep its original proportions and hard pixel edges.
      context.drawImage(sprites.portrait, 13, 45, 150, 181);
    } else {
      context.drawImage(isAction(gesture) ? sprites.actions[gesture][frame] : sprites.animations[ROW[gesture]][frame], 0, 0);
    }
  };

  const updateSignals = () => {
    const level = state === "listening" ? nivelDeVoz() : state === "speaking" ? Math.min(1, signals.cadencia / 40) : 0;
    root.style.setProperty("--fox-voice", String(reduced ? 0 : level));
    root.dataset.remote = String(Boolean(signals.remoto));
    const details = [ACTIONS[state].label];
    if (signals.remoto) details.push(`En ${signals.remoto}`);
    if (signals.pasos) details.push(`${signals.pasos} pasos`);
    if (signals.pendientes) details.push(`${signals.pendientes} permisos pendientes`);
    root.title = details.join(" · ");
    badge.textContent = ACTIONS[state].mark;
    badge.hidden = !ACTIONS[state].mark || (isAction(gesture) && !resting && frame >= 3);
  };

  const stop = () => {
    clearTimeout(timer);
    clearInterval(voiceTimer);
    timer = undefined;
    voiceTimer = undefined;
  };

  const canAnimate = () => alive && Boolean(sprites) && !reduced && !document.hidden && state !== "offline" && state !== "perdida";
  const schedule = (callback: () => void, delay: number) => {
    if (canAnimate()) timer = setTimeout(callback, delay);
  };

  const rest = () => {
    // Always return to the standalone original, including between gestures.
    resting = true;
    gesture = "blink";
    frame = 0;
    draw();
    const delay = state === "idle" ? 4200 : 3200;
    schedule(() => {
      if (state === "idle") idleBlinks++;
      // Stretch only after a genuine pause (~40 s), never while working,
      // listening, asking permission or disconnected.
      play(state === "idle" && idleBlinks % 8 === 0 ? "stretch" : "blink");
    }, delay);
  };

  const advance = () => {
    if (!canAnimate()) return;
    if (frame === 7) {
      if (gesture === "internet" || gesture === "terminal") {
        // Keep the conjured object alive while the real tool runs. Replaying
        // only the last poses avoids repeatedly taking off the same hat.
        frame = 4;
        draw();
        schedule(advance, 450);
      } else rest();
      return;
    }
    frame++;
    draw();
    schedule(advance, isAction(gesture) && frame >= 4 ? (gesture === "error" && frame === 7 ? 1100 : 450) : FRAME_MS[gesture]);
  };

  const play = (next: Gesture) => {
    resting = false;
    gesture = next;
    frame = 0;
    draw();
    schedule(advance, FRAME_MS[gesture]);
  };

  const restart = () => {
    stop();
    updateSignals();
    if (!canAnimate()) {
      resting = true;
      gesture = "blink";
      frame = 0;
      draw();
      return;
    }
    if (state === "listening") voiceTimer = setInterval(updateSignals, 80);
    if (ACTIONS[state].gesture === "blink") rest();
    else play(ACTIONS[state].gesture);
  };

  const visibilityChanged = () => restart();
  const motionChanged = (event: MediaQueryListEvent) => {
    reduced = event.matches;
    root.style.setProperty("--fox-x", "0px");
    root.style.setProperty("--fox-y", "0px");
    restart();
  };
  document.addEventListener("visibilitychange", visibilityChanged);
  preference?.addEventListener?.("change", motionChanged);
  void loadFoxSprites().then((loaded) => {
    if (!alive) return;
    sprites = loaded;
    restart();
  }).catch(() => {
    if (!alive) return;
    root.dataset.loadError = "true";
    badge.hidden = false;
    badge.textContent = "!";
    root.title = "No se ha podido cargar el diseño de Vibi";
  });
  restart();

  return {
    setState(next) {
      if (!alive || state === next) return;
      state = next;
      idleBlinks = 0;
      restart();
    },
    setSenales(next) {
      if (!alive) return;
      signals = next;
      updateSignals();
    },
    setPointer(x, y) {
      if (!alive || reduced || state === "offline" || state === "perdida") return;
      root.style.setProperty("--fox-x", `${Math.round(Math.max(-1, Math.min(1, x)) * 2)}px`);
      root.style.setProperty("--fox-y", `${Math.round(Math.max(-1, Math.min(1, y)) * 2)}px`);
    },
    clearPointer() {
      root.style.setProperty("--fox-x", "0px");
      root.style.setProperty("--fox-y", "0px");
    },
    dibujar: draw,
    resize: draw,
    dispose() {
      alive = false;
      stop();
      document.removeEventListener("visibilitychange", visibilityChanged);
      preference?.removeEventListener?.("change", motionChanged);
      root.remove();
    },
  };
}
