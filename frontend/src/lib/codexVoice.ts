/**
 * La llamada de voz con Codex, vista desde la cara.
 *
 * Con la voz de siempre la cara graba un clip, lo manda y espera; aquí la
 * conversación es continua: el audio va y viene por WebRTC directamente con
 * OpenAI, se puede interrumpir a Vibi a mitad de frase y no hay silencios de
 * corte. El servidor de Vibi solo entrega la oferta SDP y atiende lo que Codex
 * delega en él; lo que pasa allí llega por `/api/voz/codex/eventos`.
 *
 * Si algo falla **antes** de que la llamada quede conectada, `startCodexVoice`
 * lanza y la cara sigue con la voz de siempre. Una vez conectada, los fallos se
 * cuentan por `onError`.
 */
import {
  closeCompanionCodexVoice,
  openCompanionCodexVoice,
  pollCompanionCodexVoice,
  type CompanionSettings,
} from "./companionApi";
import { callarOido, publicarNivelDeVoz } from "./face/oido";

export type CodexVoiceState = "listening" | "thinking" | "speaking";

export interface CodexVoiceHandlers {
  onState(state: CodexVoiceState): void;
  onHeard(text: string): void;
  /** Vibi se ha despedido: la cara debe cerrar la conversación. */
  onClose(): void;
  onError(message: string): void;
}

export interface CodexVoiceCall {
  stop(): void;
}

const POLL_MS = 1_500;
/** Lo que se le deja a la despedida para sonar antes de colgar. */
const DESPEDIDA_MAX_MS = 6_000;
/** Por encima de esto, lo que llega del altavoz es Vibi hablando. */
const UMBRAL_SALIDA = 0.012;
/** Silencio de salida que da por terminada una frase de Vibi. */
const PAUSA_SALIDA_MS = 700;

type WebkitWindow = Window & typeof globalThis & {
  webkitAudioContext?: typeof AudioContext;
};

export function supportsCodexVoice(): boolean {
  return (
    typeof RTCPeerConnection !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function"
  );
}

const rms = (analyser: AnalyserNode, buffer: Uint8Array<ArrayBuffer>): number => {
  analyser.getByteTimeDomainData(buffer);
  let sum = 0;
  for (const value of buffer) sum += ((value - 128) / 128) ** 2;
  return Math.sqrt(sum / buffer.length);
};

export async function startCodexVoice(
  settings: CompanionSettings,
  conversationId: string,
  handlers: CodexVoiceHandlers,
): Promise<CodexVoiceCall> {
  if (!supportsCodexVoice()) {
    throw new Error("Esta ventana no admite llamadas WebRTC");
  }

  let stopped = false;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let closeTimer: ReturnType<typeof setTimeout> | null = null;
  let frame = 0;
  let state: CodexVoiceState = "listening";
  let delegando = false;
  let despidiendose = false;
  let ultimaVozSalida = 0;
  let heard = "";
  const abort = new AbortController();

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const pc = new RTCPeerConnection();
  const audio = new Audio();
  audio.autoplay = true;
  const AudioContextClass =
    window.AudioContext ?? (window as WebkitWindow).webkitAudioContext;
  const context = AudioContextClass ? new AudioContextClass() : null;
  let salida: AnalyserNode | null = null;

  const setState = (next: CodexVoiceState) => {
    if (stopped || next === state) return;
    state = next;
    handlers.onState(next);
  };

  const release = () => {
    if (stopped) return;
    stopped = true;
    abort.abort();
    if (pollTimer) clearTimeout(pollTimer);
    if (closeTimer) clearTimeout(closeTimer);
    cancelAnimationFrame(frame);
    stream.getTracks().forEach((track) => track.stop());
    pc.close();
    audio.srcObject = null;
    void context?.close().catch(() => undefined);
    callarOido();
  };

  const stop = () => {
    if (stopped) return;
    release();
    void closeCompanionCodexVoice(settings, conversationId);
  };

  // Tras la despedida se cuelga cuando Vibi termina de decirla, o al rato si
  // el final de la frase no llega a notarse.
  const despedirse = () => {
    if (despidiendose) return;
    despidiendose = true;
    closeTimer = setTimeout(() => handlers.onClose(), DESPEDIDA_MAX_MS);
  };
  const quizaColgar = () => {
    if (despidiendose && state !== "speaking") {
      if (closeTimer) clearTimeout(closeTimer);
      closeTimer = setTimeout(() => handlers.onClose(), 400);
    }
  };

  // Los dos niveles se miran en el mismo bucle: el del micrófono mueve la cara
  // mientras hablas, y el del altavoz es lo que de verdad dice si Vibi está
  // hablando —más fiable que los eventos, cuyos nombres cambian entre
  // versiones de la API realtime.
  const meter = () => {
    if (!context) return;
    const entrada = context.createAnalyser();
    entrada.fftSize = 512;
    context.createMediaStreamSource(stream).connect(entrada);
    const buffer = new Uint8Array(new ArrayBuffer(entrada.fftSize));
    const tick = () => {
      if (stopped) return;
      publicarNivelDeVoz(rms(entrada, buffer));
      if (salida) {
        const ahora = performance.now();
        if (rms(salida, buffer) > UMBRAL_SALIDA) {
          ultimaVozSalida = ahora;
          setState("speaking");
        } else if (state === "speaking" && ahora - ultimaVozSalida > PAUSA_SALIDA_MS) {
          setState(delegando ? "thinking" : "listening");
          quizaColgar();
        }
      }
      frame = requestAnimationFrame(tick);
    };
    tick();
  };

  const onDataEvent = (event: MessageEvent) => {
    let message: { type?: string; item?: { text?: unknown }; transcript?: unknown };
    try {
      message = JSON.parse(String(event.data));
    } catch {
      return;
    }
    const type = message.type ?? "";
    if (type.includes("speech_started")) {
      heard = "";
      setState("listening");
    } else if (type.includes("speech_stopped")) {
      setState("thinking");
    } else if (type === "input_transcript.added" && typeof message.item?.text === "string") {
      heard += message.item.text;
      handlers.onHeard(heard.trim());
    } else if (
      type.endsWith("input_audio_transcription.completed") &&
      typeof message.transcript === "string"
    ) {
      heard = message.transcript;
      handlers.onHeard(heard.trim());
    } else if (type === "error") {
      // No se cuelga por esto. La API realtime manda `error` también por cosas
      // inofensivas —interrumpir a Vibi cuando ya había callado, por ejemplo—
      // y tratarlo como fatal cortaba la llamada a la primera interrupción.
      console.warn("Aviso de la llamada de voz:", message);
    }
  };

  const poll = async () => {
    if (stopped) return;
    try {
      const { activa, eventos } = await pollCompanionCodexVoice(settings, conversationId);
      if (stopped) return;
      for (const evento of eventos) {
        if (evento.type === "vibi/request") {
          delegando = true;
          setState("thinking");
        } else if (evento.type === "vibi/result") {
          delegando = false;
        } else if (evento.type === "vibi/cerrar") {
          despedirse();
          quizaColgar();
        } else if (evento.type === "error") {
          console.warn("La voz de Codex ha fallado:", evento.message);
          handlers.onError(evento.message || "La voz de Codex ha fallado.");
          return;
        }
      }
      if (!activa) {
        if (despidiendose) handlers.onClose();
        else handlers.onError("La llamada de voz se ha cortado.");
        return;
      }
    } catch {
      // Un sondeo perdido no corta la llamada: el siguiente lo recupera, y el
      // servidor solo cuelga tras treinta segundos sin noticias.
    }
    pollTimer = setTimeout(() => void poll(), POLL_MS);
  };

  try {
    await context?.resume().catch(() => undefined);
    stream.getTracks().forEach((track) => pc.addTrack(track, stream));
    pc.ontrack = (event) => {
      const remoto = event.streams[0] ?? new MediaStream([event.track]);
      audio.srcObject = remoto;
      void audio.play().catch(() => undefined);
      if (context) {
        salida = context.createAnalyser();
        salida.fftSize = 512;
        context.createMediaStreamSource(remoto).connect(salida);
      }
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed") {
        handlers.onError("Se ha perdido la conexión de audio.");
      }
    };
    const channel = pc.createDataChannel("oai-events");
    channel.onmessage = onDataEvent;

    await pc.setLocalDescription(await pc.createOffer());
    const answer = await openCompanionCodexVoice(
      settings,
      conversationId,
      pc.localDescription?.sdp ?? "",
      abort.signal,
    );
    await pc.setRemoteDescription({ type: "answer", sdp: answer });
  } catch (caught) {
    // `stop` y no solo `release`: si el servidor llegó a abrir Codex y lo que
    // falló fue la respuesta, hay que colgarle también allí.
    stop();
    throw caught;
  }

  meter();
  void poll();
  return { stop };
}
