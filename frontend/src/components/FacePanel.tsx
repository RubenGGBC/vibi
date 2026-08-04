import { useQueryClient } from "@tanstack/react-query";
import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiFetch } from "../lib/api";
import { chatRuntimeKey } from "../lib/conversation";
import type { FaceState } from "../lib/face3d";
import {
  createSpeechStream,
  prewarmAcknowledgements,
  startVoiceCapture,
  supportsVoiceConversation,
  takeAcknowledgement,
  type SpeechStream,
  type VoiceCapture,
} from "../lib/voice";
import type { ChatRuntimeState, VoiceResponse } from "../types";

// Three.js pesa lo suyo y solo hace falta aquí: que viaje en su propio chunk.
const MorganaFace = lazy(() =>
  import("./MorganaFace").then((module) => ({ default: module.MorganaFace })),
);

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

export function FacePanel() {
  const supported = supportsVoiceConversation();
  const client = useQueryClient();
  const [state, setState] = useState<FaceState>("idle");
  const [error, setError] = useState<string | null>(
    supported
      ? null
      : "Este navegador no admite conversación por voz. Abre Morgana desde Chrome mediante HTTPS.",
  );
  const captureRef = useRef<VoiceCapture | null>(null);
  const speechRef = useRef<SpeechStream | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const mountedRef = useRef(true);
  const busyRef = useRef(false);

  const stopSpeaking = useCallback(() => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    speechRef.current?.cancel();
    speechRef.current = null;
  }, []);

  const stopAndSend = useCallback(async () => {
    const capture = captureRef.current;
    if (!capture || busyRef.current) return;

    captureRef.current = null;
    busyRef.current = true;
    setState("thinking");
    setError(null);

    // Identifica el turno para reconocer sus fragmentos en el canal de eventos.
    const turnId = `voz-${crypto.randomUUID()}`;
    let stream: SpeechStream | null = null;

    try {
      // Cierra el micro antes de que suene nada, o Morgana se oiría a sí misma.
      const blob = await capture.stop();
      if (!blob.size) throw new Error("empty-audio");

      // La muletilla va delante en la cola: tapa el silencio mientras piensa.
      stream = createSpeechStream(
        () => {
          if (!mountedRef.current) return;
          stopSpeaking();
          setState("idle");
        },
        { acknowledgement: takeAcknowledgement() },
      );
      speechRef.current = stream;
      const activo = stream;

      // Locuta cada frase en cuanto el modelo la cierra, sin esperar al final.
      let hablando = false;
      let fronteras = 0;
      unsubscribeRef.current = client.getQueryCache().subscribe(() => {
        if (speechRef.current !== activo) return;
        const runtime = client.getQueryData<ChatRuntimeState | null>(
          chatRuntimeKey,
        );
        if (runtime?.turn_id !== turnId) return;
        if (!hablando && runtime.text) {
          hablando = true;
          setState("speaking");
        }
        // Si el turno acaba de cerrar un bloque para usar una herramienta, ese
        // texto ("voy a buscarlo") hay que decirlo ya: es justo lo que tapa el
        // silencio mientras la herramienta trabaja.
        const boundary = runtime.boundaries > fronteras;
        fronteras = runtime.boundaries;
        activo.push(runtime.text, { boundary });
      });

      const body = new FormData();
      body.append("audio", blob, filenameFor(blob));
      body.append("client_ref", turnId);
      const result = await apiFetch<VoiceResponse>("/api/voz", {
        method: "POST",
        body,
      });
      if (!mountedRef.current || speechRef.current !== stream) return;

      // La respuesta completa cierra el turno. Si los eventos no llegaron
      // (WebSocket caído), esto es también lo que salva la locución.
      setState("speaking");
      stream.push(result.respuesta);
      stream.end();
    } catch (caught) {
      if (!mountedRef.current) return;
      stopSpeaking();
      setError(readableError(caught));
      setState("idle");
    } finally {
      busyRef.current = false;
    }
  }, [client, stopSpeaking]);

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
      stopSpeaking();
      setState("idle");
    }
    void beginListening();
  };

  useEffect(() => {
    mountedRef.current = true;
    // Deja las muletillas sintetizadas antes del primer turno: si hubiera que
    // pedirlas al vuelo llegarían tarde y no taparían nada.
    if (supported) void prewarmAcknowledgements();
    return () => {
      mountedRef.current = false;
      captureRef.current?.cancel();
      captureRef.current = null;
      stopSpeaking();
    };
  }, [supported, stopSpeaking]);

  return (
    <div className="face-panel">
      <button
        type="button"
        className={`face-stage face-${state}`}
        onClick={handleTap}
        disabled={!supported || state === "thinking"}
        aria-label="Hablar con Morgana"
        aria-pressed={state === "listening"}
      >
        <span className="face-halo" aria-hidden="true" />
        <Suspense fallback={null}>
          <MorganaFace state={state} />
        </Suspense>
      </button>

      <div className="face-feedback" aria-live="polite" aria-atomic="true">
        <p className="face-state-copy">{stateCopy[state]}</p>
        {error && <p className="face-error" role="alert">{error}</p>}
      </div>
    </div>
  );
}
