import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiFetch } from "../lib/api";
import {
  speakSpanish,
  startVoiceCapture,
  supportsVoiceConversation,
  type VoiceCapture,
} from "../lib/voice";
import type { VoiceResponse } from "../types";

type FaceState = "idle" | "listening" | "thinking" | "speaking";

const stateCopy: Record<FaceState, string> = {
  idle: "Toca a Morgana para hablar",
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
      : "Este navegador no admite conversación por voz. Abre Morgana desde Chrome mediante HTTPS.",
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
        <h1 id="face-title">Morgana</h1>
      </div>

      <button
        type="button"
        className={`face-stage face-${state}`}
        onClick={handleTap}
        disabled={!supported || state === "thinking"}
        aria-label="Hablar con Morgana"
        aria-pressed={state === "listening"}
      >
        <span className="face-halo" aria-hidden="true" />
        <span className="face-ring" aria-hidden="true" />
        <svg
          viewBox="0 0 400 400"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <g className="face-cat">
            <g className="face-ear face-ear-left">
              <path
                d="M94 150 L78 58 Q77 47 88 52 L164 94 Z"
                className="face-fur face-outline"
              />
              <path d="M104 128 L95 74 L140 100 Z" className="face-ear-inner" />
            </g>
            <g className="face-ear face-ear-right">
              <path
                d="M306 150 L322 58 Q323 47 312 52 L236 94 Z"
                className="face-fur face-outline"
              />
              <path d="M296 128 L305 74 L260 100 Z" className="face-ear-inner" />
            </g>

            <ellipse
              cx="200"
              cy="212"
              rx="134"
              ry="126"
              className="face-fur face-outline"
            />
            <path
              className="face-spark"
              d="M200 78 L205.5 90 L218 93 L205.5 96 L200 108 L194.5 96 L182 93 L194.5 90 Z"
            />

            <ellipse className="face-blush" cx="122" cy="238" rx="20" ry="12" />
            <ellipse className="face-blush" cx="278" cy="238" rx="20" ry="12" />

            <g className="face-normal-eyes">
              <g className="face-pupils">
                <g className="face-eye face-eye-left">
                  <ellipse cx="152" cy="198" rx="19" ry="24" />
                  <circle className="face-shine-primary" cx="159" cy="189" r="6" />
                  <circle className="face-shine-secondary" cx="146" cy="205" r="3.5" />
                </g>
                <g className="face-eye face-eye-right">
                  <ellipse cx="248" cy="198" rx="19" ry="24" />
                  <circle className="face-shine-primary" cx="255" cy="189" r="6" />
                  <circle className="face-shine-secondary" cx="242" cy="205" r="3.5" />
                </g>
              </g>
            </g>

            <g className="face-happy-eyes">
              <path d="M134 202 Q152 184 170 202" />
              <path d="M230 202 Q248 184 266 202" />
            </g>

            <path
              d="M191 236 Q200 229 209 236 Q205 247 200 247 Q195 247 191 236 Z"
              className="face-nose"
            />
            <g className="face-resting-mouth">
              <path d="M200 249 Q200 262 186 262 M200 249 Q200 262 214 262" />
            </g>
            <g className="face-speaking-mouth">
              <ellipse cx="200" cy="260" rx="15" ry="13" />
              <ellipse className="face-tongue" cx="200" cy="266" rx="8" ry="5" />
            </g>

            <g className="face-whiskers face-whiskers-left">
              <path d="M114 216 Q84 208 56 194" />
              <path d="M112 232 Q80 230 50 224" />
              <path d="M114 248 Q84 252 58 262" />
            </g>
            <g className="face-whiskers face-whiskers-right">
              <path d="M286 216 Q316 208 344 194" />
              <path d="M288 232 Q320 230 350 224" />
              <path d="M286 248 Q316 252 342 262" />
            </g>

            <g className="face-thinking-dots">
              <circle cx="298" cy="104" r="6" />
              <circle cx="322" cy="84" r="8" />
              <circle cx="348" cy="60" r="10" />
            </g>
          </g>
        </svg>
      </button>

      <div className="face-feedback" aria-live="polite" aria-atomic="true">
        <p className="face-state-copy">{stateCopy[state]}</p>
        {error && <p className="face-error" role="alert">{error}</p>}
      </div>
    </section>
  );
}
