import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiFetch } from "../api";
import { chatRuntimeKey } from "../conversation";
import { suscribirEventos } from "../eventBus";
import type { FaceVoiceState } from "../face";
import {
  cleanSpeechText,
  createSpeechStream,
  startVoiceCapture,
  supportsVoiceConversation,
  type SpeechStream,
  type VoiceCapture,
} from "../voice";
import type { ChatRuntimeState, MessageResponse, VoiceResponse } from "../../types";
import type { Paso } from "./tipos";

/**
 * Vibi en Estudio: lo que contesta el agente (en un bocadillo y, con la voz
 * activa, en voz alta mientras lo escribe), la narración de los pasos y el
 * micro.
 *
 * Todo lo que el alumno le dice desde aquí lleva delante «(Estudio, paso N)»:
 * así el modelo sabe que tiene que contestar montando la escena. Los turnos
 * son de la conversación activa, la misma del chat.
 */

const CLAVE_PREFERENCIA = "vibi.estudio.voz";

export function leerPreferenciaVoz(): boolean {
  try {
    return window.localStorage.getItem(CLAVE_PREFERENCIA) !== "no";
  } catch {
    return true;
  }
}

export function guardarPreferenciaVoz(activa: boolean): void {
  try {
    window.localStorage.setItem(CLAVE_PREFERENCIA, activa ? "si" : "no");
  } catch {
    // Sin almacenamiento la preferencia dura lo que la pestaña.
  }
}

/** Lo que dice Vibi al llegar a un paso: lo que cuenta, lo que te toca y la pregunta. */
export function narracionDePaso(paso: Paso): string {
  return [paso.texto, paso.tarea, paso.pregunta?.enunciado]
    .map((parte) => parte?.trim())
    .filter(Boolean)
    .join(" ");
}

const nombreDeArchivo = (audio: Blob): string => {
  if (audio.type.includes("mp4")) return "voz.m4a";
  if (audio.type.includes("ogg")) return "voz.ogg";
  return "voz.webm";
};

const errorLegible = (error: unknown): string => {
  if (error instanceof ApiError) return error.message;
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "Activa el permiso del micrófono para hablar con Vibi.";
  }
  if (error instanceof DOMException && error.name === "NotFoundError") {
    return "No encuentro ningún micrófono.";
  }
  return "No he podido contestarte. Inténtalo otra vez.";
};

export interface VozTutor {
  estado: FaceVoiceState;
  /** Lo último que ha contestado Vibi, limpio. Vacío si no hay nada que enseñar. */
  bocadillo: string;
  /** Qué está haciendo mientras piensa («Montando la escena…»). */
  etiqueta: string;
  error: string | null;
  puedeEscuchar: boolean;
  /** Dice un texto en voz alta (pistas, explicaciones). Sin voz, nada. */
  decir: (texto: string) => void;
  /** Como `decir`, pero no interrumpe al agente: si está en un turno, manda él. */
  narrar: (texto: string) => void;
  callar: () => void;
  /** Le manda al agente lo que ha escrito o pulsado el alumno. */
  preguntar: (texto: string) => void;
  /** Empieza a escuchar o, si ya escuchaba, envía lo dicho. */
  alternarMicro: () => void;
  cerrarBocadillo: () => void;
}

export function useVozTutor(activa: boolean, prefijo: () => string): VozTutor {
  const client = useQueryClient();
  const [estado, setEstado] = useState<FaceVoiceState>("idle");
  const [bocadillo, setBocadillo] = useState("");
  const [etiqueta, setEtiqueta] = useState("");
  const [error, setError] = useState<string | null>(null);
  const puedeEscuchar = supportsVoiceConversation();

  const activaRef = useRef(activa);
  activaRef.current = activa;
  const prefijoRef = useRef(prefijo);
  prefijoRef.current = prefijo;
  const voz = useRef<SpeechStream | null>(null);
  const captura = useRef<VoiceCapture | null>(null);
  // El turno del agente que se está siguiendo, y los que ya no hay que tocar.
  const turno = useRef<{ id: string; fronteras: number } | null>(null);
  const terminados = useRef(new Set<string>());
  // Se le ha pedido algo al agente desde aquí y aún no ha contestado.
  const esperando = useRef(false);

  const reposo = useCallback(() => {
    setEstado((actual) => (actual === "speaking" || actual === "thinking" ? "idle" : actual));
  }, []);

  const nuevaVoz = useCallback((): SpeechStream | null => {
    voz.current?.cancel();
    voz.current = null;
    if (!activaRef.current) return null;
    const stream = createSpeechStream(() => {
      if (voz.current !== stream) return;
      voz.current = null;
      reposo();
    });
    voz.current = stream;
    return stream;
  }, [reposo]);

  const callar = useCallback(() => {
    voz.current?.cancel();
    voz.current = null;
    setEstado((actual) => (actual === "speaking" ? "idle" : actual));
  }, []);

  const decir = useCallback(
    (texto: string) => {
      if (!texto.trim()) return;
      const stream = nuevaVoz();
      if (!stream) return;
      setEstado("speaking");
      stream.push(texto);
      stream.end();
    },
    [nuevaVoz],
  );

  const narrar = useCallback(
    (texto: string) => {
      const enTurno = client.getQueryData<ChatRuntimeState | null>(chatRuntimeKey);
      if (turno.current || esperando.current || enTurno) return;
      decir(texto);
    },
    [client, decir],
  );

  /** El turno ha terminado con este texto: se enseña y, si hacía falta, se dice. */
  const cerrarTurno = useCallback(
    (texto: string) => {
      turno.current = null;
      esperando.current = false;
      setEtiqueta("");
      setBocadillo(cleanSpeechText(texto));
      if (voz.current && texto.trim()) {
        setEstado("speaking");
        voz.current.push(texto);
        voz.current.end();
      } else {
        reposo();
      }
    },
    [reposo],
  );

  // Lo que el agente va escribiendo: al bocadillo y, frase a frase, a la voz.
  useEffect(
    () =>
      client.getQueryCache().subscribe(() => {
        const runtime = client.getQueryData<ChatRuntimeState | null>(chatRuntimeKey);
        if (!runtime) {
          if (!esperando.current && !turno.current) {
            setEtiqueta("");
            setEstado((actual) => (actual === "thinking" ? "idle" : actual));
          }
          return;
        }
        if (terminados.current.has(runtime.turn_id)) return;
        if (turno.current?.id !== runtime.turn_id) {
          if (turno.current) terminados.current.add(turno.current.id);
          turno.current = { id: runtime.turn_id, fronteras: 0 };
          esperando.current = false;
          voz.current?.cancel();
          voz.current = null;
          setBocadillo("");
          setEstado("thinking");
        }
        if (!runtime.text) {
          setEtiqueta(runtime.label);
          return;
        }
        if (!voz.current) nuevaVoz();
        setEstado(voz.current ? "speaking" : "thinking");
        setEtiqueta(runtime.fase === "herramienta" ? runtime.label : "");
        const boundary = runtime.boundaries > turno.current.fronteras;
        turno.current.fronteras = runtime.boundaries;
        voz.current?.push(runtime.text, { boundary });
        setBocadillo(cleanSpeechText(runtime.text));
      }),
    [client, nuevaVoz],
  );

  // El mensaje completo cierra el turno. Si no llegó ningún trozo (WebSocket
  // caído, respuesta rápida), es lo único que hay.
  useEffect(
    () =>
      suscribirEventos((evento) => {
        if (evento.tipo !== "chat_message" || evento.message.role !== "assistant") return;
        const actual = turno.current;
        if (!actual && !esperando.current) return;
        if (actual) terminados.current.add(actual.id);
        else nuevaVoz();
        cerrarTurno(evento.message.content);
      }),
    [cerrarTurno, nuevaVoz],
  );

  const esperarRespuesta = useCallback(
    async (peticion: () => Promise<MessageResponse | VoiceResponse>) => {
      callar();
      if (turno.current) terminados.current.add(turno.current.id);
      turno.current = null;
      setError(null);
      setBocadillo("");
      setEtiqueta("");
      setEstado("thinking");
      esperando.current = true;
      try {
        const resultado = await peticion();
        // Sin trozos ni mensaje por el WebSocket: lo dice la respuesta.
        if (esperando.current) {
          nuevaVoz();
          cerrarTurno("respuesta" in resultado ? resultado.respuesta : "");
        }
      } catch (fallo) {
        esperando.current = false;
        setEtiqueta("");
        setError(errorLegible(fallo));
        setEstado("idle");
      }
    },
    [callar, cerrarTurno, nuevaVoz],
  );

  const preguntar = useCallback(
    (texto: string) => {
      const limpio = texto.trim();
      if (!limpio) return;
      const conPrefijo = limpio.startsWith("(") ? limpio : `${prefijoRef.current()} ${limpio}`;
      void esperarRespuesta(() =>
        apiFetch<MessageResponse>("/api/mensaje", {
          method: "POST",
          body: JSON.stringify({ texto: conPrefijo, client_ref: `estudio-${crypto.randomUUID()}` }),
        }),
      );
    },
    [esperarRespuesta],
  );

  const enviarVoz = useCallback(async () => {
    const enCurso = captura.current;
    if (!enCurso) return;
    captura.current = null;
    await esperarRespuesta(async () => {
      const audio = await enCurso.stop();
      if (!audio.size) throw new Error("sin audio");
      const cuerpo = new FormData();
      cuerpo.append("audio", audio, nombreDeArchivo(audio));
      cuerpo.append("client_ref", `estudio-${crypto.randomUUID()}`);
      cuerpo.append("prefijo", prefijoRef.current());
      return apiFetch<VoiceResponse>("/api/voz", { method: "POST", body: cuerpo });
    });
  }, [esperarRespuesta]);

  const alternarMicro = useCallback(() => {
    if (captura.current) {
      void enviarVoz();
      return;
    }
    if (!puedeEscuchar) return;
    callar();
    setError(null);
    setEstado("listening");
    startVoiceCapture(() => void enviarVoz())
      .then((nueva) => {
        captura.current = nueva;
      })
      .catch((fallo: unknown) => {
        setError(errorLegible(fallo));
        setEstado("idle");
      });
  }, [callar, enviarVoz, puedeEscuchar]);

  const cerrarBocadillo = useCallback(() => setBocadillo(""), []);

  useEffect(() => {
    if (!activa) callar();
  }, [activa, callar]);

  useEffect(
    () => () => {
      captura.current?.cancel();
      voz.current?.cancel();
    },
    [],
  );

  return {
    estado,
    bocadillo,
    etiqueta,
    error,
    puedeEscuchar,
    decir,
    narrar,
    callar,
    preguntar,
    alternarMicro,
    cerrarBocadillo,
  };
}
