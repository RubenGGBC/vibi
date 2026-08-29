import { useCallback, useEffect, useRef, useState } from "react";

import { TapToTalkFace, type TapToTalkState } from "./TapToTalkFace";
import { MessageComposer } from "./MessageComposer";
import { ApiError } from "../lib/api";
import { transcribirEntrevista, turnoEntrevista } from "../lib/perfilApi";
import { speakSpanish, startVoiceCapture, supportsVoiceConversation, type VoiceCapture } from "../lib/voice";
import type { ResumenEntrevista, TurnoHistorial } from "../types";

const stateCopy: Record<TapToTalkState, string> = {
  idle: "Toca a Vibi para hablar, o escribe abajo",
  listening: "Te escucho · toca para enviar",
  thinking: "Estoy pensando",
  speaking: "Toca para interrumpir",
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
  }
  return "No he podido continuar la entrevista. Inténtalo de nuevo.";
};

/**
 * El paso "preguntas" de la entrevista, como conversación: la cara narra
 * cada pregunta por voz, y respondes hablando (toca la cara) o escribiendo
 * abajo. Cuando el servidor decide que ya cubrió los cuatro temas, entrega el
 * resumen estructurado que antes salía de las cuatro casillas de texto.
 */
export function EntrevistaConversacion({
  onTerminado,
}: {
  onTerminado: (resumen: ResumenEntrevista) => void;
}) {
  const soportaVoz = supportsVoiceConversation();
  const [historial, setHistorial] = useState<TurnoHistorial[]>([]);
  const [state, setState] = useState<TapToTalkState>("thinking");
  const [error, setError] = useState("");
  const captureRef = useRef<VoiceCapture | null>(null);
  const speechCancelRef = useRef<(() => void) | null>(null);
  const mountedRef = useRef(true);
  const busyRef = useRef(false);
  const pendienteRef = useRef<TurnoHistorial[] | null>(null);
  const arrancadaRef = useRef(false);

  const avanzar = useCallback(async (siguienteHistorial: TurnoHistorial[]) => {
    pendienteRef.current = siguienteHistorial;
    setHistorial(siguienteHistorial);
    setState("thinking");
    setError("");
    try {
      const turno = await turnoEntrevista(siguienteHistorial);
      if (!mountedRef.current) return;
      pendienteRef.current = null;
      const conRespuesta: TurnoHistorial[] = [
        ...siguienteHistorial,
        { rol: "vibi", texto: turno.vibi_dice },
      ];
      setHistorial(conRespuesta);
      setState("speaking");
      speechCancelRef.current = speakSpanish(turno.vibi_dice, () => {
        if (!mountedRef.current) return;
        speechCancelRef.current = null;
        if (turno.terminado && turno.resumen) {
          onTerminado(turno.resumen);
        } else {
          setState("idle");
        }
      });
    } catch (caught) {
      if (!mountedRef.current) return;
      setError(readableError(caught));
      setState("idle");
    }
  }, [onTerminado]);

  useEffect(() => {
    mountedRef.current = true;
    if (!arrancadaRef.current) {
      arrancadaRef.current = true;
      void avanzar([]);
    }
    return () => {
      mountedRef.current = false;
      captureRef.current?.cancel();
      speechCancelRef.current?.();
    };
    // Solo arranca una vez: `avanzar` cambia de identidad con el historial y
    // no debe disparar este efecto de nuevo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reintentar = () => {
    void avanzar(pendienteRef.current ?? historial);
  };

  const responderConTexto = (texto: string) => {
    if (state === "thinking") return;
    void avanzar([...historial, { rol: "usuario", texto }]);
  };

  const detenerYEnviar = useCallback(async () => {
    const capture = captureRef.current;
    if (!capture || busyRef.current) return;
    captureRef.current = null;
    busyRef.current = true;
    setState("thinking");
    setError("");
    try {
      const blob = await capture.stop();
      if (!blob.size) throw new Error("empty-audio");
      const { transcripcion } = await transcribirEntrevista(blob, filenameFor(blob));
      if (!mountedRef.current) return;
      void avanzar([...historial, { rol: "usuario", texto: transcripcion }]);
    } catch (caught) {
      if (!mountedRef.current) return;
      setError(readableError(caught));
      setState("idle");
    } finally {
      busyRef.current = false;
    }
  }, [avanzar, historial]);

  const empezarAEscuchar = useCallback(async () => {
    if (!soportaVoz || busyRef.current || captureRef.current) return;
    busyRef.current = true;
    setError("");
    setState("listening");
    try {
      const capture = await startVoiceCapture(() => void detenerYEnviar());
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
  }, [detenerYEnviar, soportaVoz]);

  const tocarLaCara = () => {
    if (state === "thinking") return;
    if (state === "listening") {
      void detenerYEnviar();
      return;
    }
    if (state === "speaking") {
      speechCancelRef.current?.();
      speechCancelRef.current = null;
      setState("idle");
      return;
    }
    void empezarAEscuchar();
  };

  return (
    <div className="entrevista-conversacion">
      <TapToTalkFace state={state} onTap={tocarLaCara} disabled={!soportaVoz} />
      <p className="entrevista-conversacion-estado" aria-live="polite">
        {stateCopy[state]}
      </p>

      <div className="entrevista-conversacion-hilo" aria-live="polite">
        {historial.map((turno, idx) => (
          <div
            key={idx}
            className={`bubble-row bubble-${turno.rol === "vibi" ? "assistant" : "user"}`}
          >
            {turno.rol === "vibi" && <span className="bubble-avatar">✦</span>}
            <p>{turno.texto}</p>
          </div>
        ))}
      </div>

      {error && (
        <p className="entrevista-conversacion-error" role="alert">
          {error}{" "}
          <button type="button" className="perfil-btn-secondary" onClick={reintentar}>
            Reintentar
          </button>
        </p>
      )}

      <MessageComposer
        label="Responder a Vibi"
        placeholder="Escribe tu respuesta…"
        submitLabel="Enviar respuesta"
        pending={state === "thinking"}
        onSubmit={responderConTexto}
      />
    </div>
  );
}
