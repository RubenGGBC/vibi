import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import type { FaceState } from "../lib/face3d";
import {
  clearCompanionSettings,
  closeCompanionConversation,
  CompanionApiError,
  loadCompanionSettings,
  openCompanionConversation,
  registerCompanion,
  requestCompanionSpeech,
  saveCompanionSettings,
  sendCompanionVoice,
  type CompanionSettings,
} from "../lib/companionApi";
import {
  createSpeechStream,
  startVoiceCapture,
  type SpeechStream,
  type VoiceCapture,
} from "../lib/voice";
import { MorganaFace } from "./MorganaFace";

type CompanionState =
  | "setup"
  | "sleeping"
  | "opening"
  | "listening"
  | "thinking"
  | "speaking"
  | "closing"
  | "error";

const stateCopy: Record<Exclude<CompanionState, "setup" | "sleeping">, string> = {
  opening: "Abriendo una conversación nueva",
  listening: "Te escucho",
  thinking: "Estoy pensando",
  speaking: "Te respondo",
  closing: "Guardando la conversación",
  error: "Necesito atención",
};

const faceState = (state: CompanionState): FaceState => {
  if (state === "listening" || state === "thinking" || state === "speaking") {
    return state;
  }
  return "idle";
};

const filenameFor = (blob: Blob): string => {
  if (blob.type.includes("mp4")) return "voz.m4a";
  if (blob.type.includes("ogg")) return "voz.ogg";
  if (blob.type.includes("wav")) return "voz.wav";
  return "voz.webm";
};

const readableError = (error: unknown): string => {
  if (error instanceof CompanionApiError) return error.message;
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "Permite el micrófono para que pueda escucharte.";
  }
  if (error instanceof DOMException && error.name === "NotFoundError") {
    return "No encuentro ningún micrófono disponible.";
  }
  if (error instanceof Error && error.message) return error.message;
  return "No he podido completar el turno. Comprueba que Docker siga activo.";
};

export function CompanionApp() {
  const [settings, setSettings] = useState<CompanionSettings | null>(
    loadCompanionSettings,
  );
  const [state, setState] = useState<CompanionState>(
    settings ? "sleeping" : "setup",
  );
  const [error, setError] = useState("");
  const [heard, setHeard] = useState("");
  const captureRef = useRef<VoiceCapture | null>(null);
  const speechRef = useRef<SpeechStream | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const closingRef = useRef(false);
  const activeRef = useRef(false);
  const mountedRef = useRef(true);
  const settingsRef = useRef(settings);
  const beginListeningRef = useRef<() => void>(() => undefined);
  const sendCurrentRef = useRef<() => void>(() => undefined);
  const endSessionRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);

  // La conversación dura lo que dura la sesión de voz: al cerrar la cara se
  // archiva en el servidor para que el próximo despertar empiece en blanco.
  const endSession = useCallback(async (options?: { yaArchivada?: boolean }) => {
    if (closingRef.current) return;
    const wasActive = activeRef.current;
    activeRef.current = false;
    captureRef.current?.cancel();
    captureRef.current = null;
    speechRef.current?.cancel();
    speechRef.current = null;
    requestRef.current?.abort();
    requestRef.current = null;
    const currentSettings = settingsRef.current;
    const conversationId = sessionIdRef.current;
    if (
      wasActive &&
      currentSettings &&
      conversationId &&
      !options?.yaArchivada
    ) {
      closingRef.current = true;
      setState("closing");
      setError("");
      try {
        await closeCompanionConversation(currentSettings, conversationId);
      } catch (caught) {
        closingRef.current = false;
        if (!mountedRef.current) return;
        activeRef.current = true;
        setState("error");
        setError(
          `${readableError(caught)} Pulsa de nuevo para reintentar el cierre.`,
        );
        return;
      }
    }
    closingRef.current = false;
    sessionIdRef.current = null;
    setState(currentSettings ? "sleeping" : "setup");
    setError("");
    setHeard("");
    void invoke("end_conversation");
  }, []);
  endSessionRef.current = () => void endSession();

  const sendCurrent = useCallback(async () => {
    const capture = captureRef.current;
    const currentSettings = settingsRef.current;
    const conversationId = sessionIdRef.current;
    if (
      !capture ||
      !currentSettings ||
      !conversationId ||
      !activeRef.current
    ) return;

    captureRef.current = null;
    setState("thinking");
    setError("");
    const controller = new AbortController();
    requestRef.current = controller;

    try {
      const blob = await capture.stop();
      if (!blob.size) throw new Error("No he oído ninguna voz.");
      const result = await sendCompanionVoice(
        currentSettings,
        blob,
        filenameFor(blob),
        conversationId,
        controller.signal,
      );
      requestRef.current = null;
      if (!mountedRef.current || !activeRef.current) return;
      setHeard(result.transcripcion);
      if (result.via === "cerrar") {
        // La despedida ya archivó la conversación al procesar el audio.
        void endSession({ yaArchivada: true });
        return;
      }

      setState("speaking");
      const stream = createSpeechStream(
        () => {
          if (!mountedRef.current || speechRef.current !== stream) return;
          speechRef.current = null;
          if (activeRef.current) beginListeningRef.current();
        },
        {
          requestAudio: (text, signal) =>
            requestCompanionSpeech(currentSettings, text, signal),
        },
      );
      speechRef.current = stream;
      stream.push(result.respuesta);
      stream.end();
    } catch (caught) {
      if (!mountedRef.current || !activeRef.current) return;
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      if (caught instanceof CompanionApiError && caught.status === 401) {
        clearCompanionSettings();
        settingsRef.current = null;
        setSettings(null);
        activeRef.current = false;
        setState("setup");
        setError("Este PC fue desvinculado. Inicia sesión para volver a conectarlo.");
        return;
      }
      setState("error");
      setError(readableError(caught));
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, [endSession]);
  sendCurrentRef.current = () => void sendCurrent();

  const beginListening = useCallback(async () => {
    if (!activeRef.current || !settingsRef.current || captureRef.current) return;
    speechRef.current?.cancel();
    speechRef.current = null;
    setState("listening");
    setError("");
    try {
      const capture = await startVoiceCapture(() => sendCurrentRef.current());
      if (!mountedRef.current || !activeRef.current) {
        capture.cancel();
        return;
      }
      captureRef.current = capture;
    } catch (caught) {
      if (!mountedRef.current || !activeRef.current) return;
      setState("error");
      setError(readableError(caught));
    }
  }, []);
  beginListeningRef.current = () => void beginListening();

  const wake = useCallback(() => {
    const currentSettings = settingsRef.current;
    if (!currentSettings) {
      setState("setup");
      setError("Vincula este PC antes de activar la voz.");
      return;
    }
    if (activeRef.current) return;
    activeRef.current = true;
    setHeard("");
    setError("");
    setState("opening");
    // El detector se pausa a sí mismo antes de emitir el despertar. No usamos
    // set_listener_paused aquí porque esa orden representa la pausa manual de
    // la bandeja y evitaría que la despedida reanudase la escucha.
    void openCompanionConversation(currentSettings)
      .then((conversationId) => {
        if (!mountedRef.current || !activeRef.current) {
          void closeCompanionConversation(
            currentSettings,
            conversationId,
          ).catch(() => undefined);
          return;
        }
        sessionIdRef.current = conversationId;
        beginListeningRef.current();
      })
      .catch((caught) => {
        if (!mountedRef.current || !activeRef.current) return;
        if (caught instanceof CompanionApiError && caught.status === 401) {
          clearCompanionSettings();
          settingsRef.current = null;
          setSettings(null);
          activeRef.current = false;
          setState("setup");
          setError(
            "Este PC fue desvinculado. Inicia sesión para volver a conectarlo.",
          );
          void invoke("end_conversation");
          return;
        }
        setState("error");
        setError(readableError(caught));
      });
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    const unlisteners: UnlistenFn[] = [];
    let cancelled = false;
    void Promise.all([
      listen("morgana://wake", wake),
      // Alt+F4 y cualquier otro cierre de ventana se resuelven en Rust: sin
      // este aviso la conversación seguiría viva en el próximo despertar.
      listen("morgana://end-session", () => endSessionRef.current()),
      listen<string>("morgana://listener-error", (event) => {
        setState("error");
        setError(event.payload);
      }),
    ]).then((items) => {
      if (cancelled) items.forEach((unlisten) => unlisten());
      else unlisteners.push(...items);
    });

    if (settingsRef.current) {
      void invoke<string | null>("listener_error").then((listenerError) => {
        if (listenerError) {
          setState("error");
          setError(listenerError);
        } else {
          void invoke("end_conversation");
        }
      });
    }

    return () => {
      cancelled = true;
      mountedRef.current = false;
      unlisteners.forEach((unlisten) => unlisten());
      captureRef.current?.cancel();
      speechRef.current?.cancel();
      requestRef.current?.abort();
    };
  }, [wake]);

  if (!settings) {
    return (
      <SetupPanel
        initialError={error}
        onRegistered={(created) => {
          saveCompanionSettings(created);
          settingsRef.current = created;
          setSettings(created);
          setState("sleeping");
          setError("");
          void invoke("end_conversation");
        }}
      />
    );
  }

  const copy =
    state === "opening" ||
    state === "listening" ||
    state === "thinking" ||
    state === "speaking" ||
    state === "closing" ||
    state === "error"
      ? stateCopy[state]
      : "";

  return (
    <main className={`companion-shell companion-${state}`}>
      <div className="companion-drag" data-tauri-drag-region aria-hidden="true" />
      <button
        type="button"
        className="companion-face"
        onClick={() => void endSession()}
        aria-label="Cerrar la conversación con Morgana"
      >
        <span className="companion-halo" aria-hidden="true" />
        <MorganaFace state={faceState(state)} />
      </button>
      <section className="companion-feedback" aria-live="polite">
        <p>{copy}</p>
        {heard && state !== "error" && <span>“{heard}”</span>}
        {error && <span className="companion-error">{error}</span>}
      </section>
      {state !== "sleeping" && (
        <button type="button" className="companion-close" onClick={() => void endSession()}>
          Clic para terminar
        </button>
      )}
    </main>
  );
}

function SetupPanel({
  initialError,
  onRegistered,
}: {
  initialError: string;
  onRegistered: (settings: CompanionSettings) => void;
}) {
  const [apiBase, setApiBase] = useState("http://127.0.0.1:8000");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [nodeName, setNodeName] = useState("Servidor Windows");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(initialError);

  useEffect(() => setError(initialError), [initialError]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const created = await registerCompanion({
        apiBase,
        name,
        password,
        nodeName,
      });
      setPassword("");
      onRegistered(created);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="companion-setup">
      <div className="setup-sigil" aria-hidden="true">✦</div>
      <p className="setup-eyebrow">Vincular este PC</p>
      <h1>Morgana</h1>
      <form onSubmit={submit}>
        <label>
          <span>Servidor</span>
          <input value={apiBase} onChange={(event) => setApiBase(event.target.value)} required />
        </label>
        <label>
          <span>Nombre</span>
          <input autoComplete="username" value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label>
          <span>Contraseña</span>
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        </label>
        <label>
          <span>Nombre del PC</span>
          <input value={nodeName} onChange={(event) => setNodeName(event.target.value)} required />
        </label>
        {error && <p className="setup-error">{error}</p>}
        <button disabled={pending}>{pending ? "Vinculando…" : "Vincular y escuchar"}</button>
      </form>
    </main>
  );
}
