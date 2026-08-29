import { useCallback, useEffect, useRef, useState } from "react";

import { TapToTalkFace, type TapToTalkState } from "../components/TapToTalkFace";
import { ApiError, apiFetch } from "../lib/api";
import {
  speakSpanish,
  startVoiceCapture,
  supportsVoiceConversation,
  type VoiceCapture,
} from "../lib/voice";
import type { VoiceResponse } from "../types";

type FaceState = TapToTalkState;

const stateCopy: Record<FaceState, string> = {
  idle: "Toca a Vibi para hablar",
  listening: "Te escucho · toca para enviar",
  thinking: "Estoy pensando",
  speaking: "Te respondo · toca para interrumpir",
};

const filenameFor = (blob: Blob): string => {
  if (blob.type.includes("mp4")) return "voz.m4a";
  if (blob.type.includes("ogg")) return "voz.ogg";
  if (blob.type.includes("wav")) return "voz.wav";
  return "voz.webm";
};

const readableError = (error: unknown): string => {
  if (error instanceof ApiError) return error.message;
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") {
      return "Activa el permiso del micrófono en Chrome y vuelve a tocarme.";
    }
    if (error.name === "NotFoundError") {
      return "No encuentro ningún micrófono disponible en este dispositivo.";
    }
    if (error.name === "NotSupportedError") return error.message;
  }
  return "No he podido escucharte. Comprueba la conexión e inténtalo otra vez.";
};

export function FacePage() {
  const supported = supportsVoiceConversation();
  const [state, setState] = useState<FaceState>("idle");
  const [error, setError] = useState<string | null>(
    supported
      ? null
      : "Este navegador no admite conversación por voz. Abre Vibi desde Chrome mediante HTTPS.",
  );
  const captureRef = useRef<VoiceCapture | null>(null);
  const speechCancelRef = useRef<(() => void) | null>(null);
  const mountedRef = useRef(true);
  const busyRef = useRef(false);

  const stopAndSend = useCallback(async () => {
    const capture = captureRef.current;
    if (!capture || busyRef.current) return;

    captureRef.current = null;
    busyRef.current = true;
    setState("thinking");
    setError(null);

    try {
      const blob = await capture.stop();
      if (!blob.size) throw new Error("empty-audio");

      const body = new FormData();
      body.append("audio", blob, filenameFor(blob));
      const result = await apiFetch<VoiceResponse>("/api/voz", {
        method: "POST",
        body,
      });
      if (!mountedRef.current) return;

      setState("speaking");
      speechCancelRef.current = speakSpanish(result.respuesta, () => {
        if (!mountedRef.current) return;
        speechCancelRef.current = null;
        setState("idle");
      });
    } catch (caught) {
      if (!mountedRef.current) return;
      setError(readableError(caught));
      setState("idle");
    } finally {
      busyRef.current = false;
    }
  }, []);

  const beginListening = useCallback(async () => {
    if (!supported || busyRef.current || captureRef.current) return;
    busyRef.current = true;
    setError(null);
    setState("listening");

    try {
      const capture = await startVoiceCapture(() => {
        void stopAndSend();
      });
      if (!mountedRef.current) {
        capture.cancel();
        return;
      }
      captureRef.current = capture;
    } catch (caught) {
      if (!mountedRef.current) return;
      setError(readableError(caught));
      setState("idle");
    } finally {
      busyRef.current = false;
    }
  }, [stopAndSend, supported]);

  const handleTap = () => {
    if (state === "thinking") return;
    if (state === "listening") {
      void stopAndSend();
      return;
    }
    if (state === "speaking") {
      speechCancelRef.current?.();
      speechCancelRef.current = null;
      setState("idle");
    }
    void beginListening();
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      captureRef.current?.cancel();
      captureRef.current = null;
      speechCancelRef.current?.();
      speechCancelRef.current = null;
    };
  }, []);

  return (
    <section className="face-page" aria-labelledby="face-title">
      <div className="face-heading">
        <p className="eyebrow">Conversación por voz</p>
        <h1 id="face-title">Vibi</h1>
      </div>

      <TapToTalkFace state={state} onTap={handleTap} disabled={!supported} />

      <div className="face-feedback" aria-live="polite" aria-atomic="true">
        <p className="face-state-copy">{stateCopy[state]}</p>
        {error && <p className="face-error" role="alert">{error}</p>}
      </div>
    </section>
  );
}
