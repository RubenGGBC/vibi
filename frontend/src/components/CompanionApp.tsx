import { useQuery, useQueryClient } from "@tanstack/react-query";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { PanelRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { chatRuntimeKey } from "../lib/conversation";
import type { FaceState } from "../lib/face";
import { useFaceMood } from "../lib/faceMood";
import { notificar } from "../lib/notifications";
import { fetchNodeApprovals, nodeApprovalsKey } from "../lib/nodeApprovals";
import { useEvents } from "../lib/useEvents";
import type { ChatRuntimeState, NodeOrder } from "../types";
import {
  applyCompanionSession,
  clearCompanionSettings,
  closeCompanionConversation,
  connectCompanionConsole,
  CompanionApiError,
  loadCompanionSettings,
  openCompanionConversation,
  registerCompanion,
  reportCompanionPresence,
  requestCompanionSpeech,
  saveCompanionSettings,
  sendCompanionVoice,
  type CompanionSettings,
} from "../lib/companionApi";
import { suscribirEventos } from "../lib/eventBus";
import {
  createSpeechStream,
  prewarmAcknowledgements,
  speakSpanish,
  startVoiceCapture,
  takeAcknowledgement,
  type SpeechStream,
  type VoiceCapture,
} from "../lib/voice";
import { VibiFace } from "./VibiFace";

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
  // Abrir la conversación y archivarla son esperas cortas, y esperar ya tiene
  // cara. El error es lo único que merece una propia.
  if (state === "opening" || state === "closing") return "thinking";
  if (state === "error") return "alert";
  return "idle";
};

/** Mientras dura la sesión de voz la cara es tuya, y nada de fuera la desvía. */
const enConversacion = (state: CompanionState): boolean =>
  state !== "sleeping" && state !== "setup";

/**
 * Cada cuánto se repite «sigo despierta». Holgado respecto a lo que el servidor
 * espera antes de darlo por caducado, para que un render lento no lo mate.
 */
const PRESENCIA_LATIDO_MS = 8_000;

const filenameFor = (blob: Blob): string => {
  if (blob.type.includes("mp4")) return "voz.m4a";
  if (blob.type.includes("ogg")) return "voz.ogg";
  if (blob.type.includes("wav")) return "voz.wav";
  return "voz.webm";
};

/**
 * Lo que tarda la despedida en verse. `end_conversation` esconde la ventana en
 * Rust sin preguntar, así que la animación de salida solo existe si se le deja
 * este hueco por delante.
 */
const DESPEDIDA_MS = 260;

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
  // El canal de eventos es lo que deja a la cara locutar sobre la marcha; sin
  // él Vibi solo puede decir la respuesta final, ya con la herramienta hecha.
  // Se le pasa el JWT como clave para que reconecte cuando aparezca: el
  // companion arranca con la voz funcionando y sin sesión de consola, y antes
  // se quedaba fuera del canal para siempre sin decir nada.
  useEvents(loadCompanionSettings()?.userToken ?? null);
  // Lo que Windows ha notificado y todavía no se ha dicho. Es una cola y no una
  // locución directa porque un aviso no puede cortar a Vibi a mitad de frase:
  // si está en un turno, espera a que acabe.
  const avisosPendientes = useRef<string[]>([]);
  const diciendoAviso = useRef(false);
  // Solo existe para volver a disparar el efecto que vacía la cola: cuando
  // entra un aviso y cuando termina de decirse el anterior. Su valor no
  // significa nada, solo que la cola ha cambiado.
  const [avisoDicho, setAvisoDicho] = useState(0);
  const client = useQueryClient();
  const [settings, setSettings] = useState<CompanionSettings | null>(
    loadCompanionSettings,
  );
  const [state, setState] = useState<CompanionState>(
    settings ? "sleeping" : "setup",
  );
  const [error, setError] = useState("");
  const [heard, setHeard] = useState("");
  const [saliendo, setSaliendo] = useState(false);
  const captureRef = useRef<VoiceCapture | null>(null);
  const speechRef = useRef<SpeechStream | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const closingRef = useRef(false);
  const activeRef = useRef(false);
  const mountedRef = useRef(true);
  const settingsRef = useRef(settings);
  const beginListeningRef = useRef<() => void>(() => undefined);
  const sendCurrentRef = useRef<() => void>(() => undefined);
  const endSessionRef = useRef<() => void>(() => undefined);
  const altTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const altWokenRef = useRef(false);

  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);

  // Las notificaciones del ordenador, dichas en voz alta. Llegan por el mismo
  // canal que el resto de avisos y se distinguen por `hablar`: por ahí también
  // pasan cosas que solo se leen —una tarea que termina, un archivo que llega—
  // y ponerlas todas a sonar sería insufrible.
  useEffect(
    () =>
      suscribirEventos((evento) => {
        if (evento.tipo !== "notificacion" || !evento.hablar) return;
        if (!evento.texto?.trim()) return;
        avisosPendientes.current.push(evento.texto);
        // Hay que sacudir el efecto de abajo a mano. La cola es un `ref`, y
        // empujar en un ref no provoca render: sin esto, un aviso que llega
        // con Vibi ya en reposo se queda ahí hasta que algo *más* cambie el
        // estado, que puede no pasar nunca. No se veía porque el companion no
        // recibía ningún evento; en cuanto el canal funcionó, salió.
        setAvisoDicho((contador) => contador + 1);
      }),
    [],
  );

  // El servidor no puede ver esta ventana, así que se le cuenta. Mientras la
  // cara esté despierta se repite, porque un cierre de golpe no manda nada y
  // sin latido el servidor se quedaría creyendo que sigues hablando.
  useEffect(() => {
    if (!settings) return;
    const despierta = enConversacion(state);
    void reportCompanionPresence(settings, despierta);
    if (!despierta) return;
    const latido = setInterval(() => {
      void reportCompanionPresence(settings, true);
    }, PRESENCIA_LATIDO_MS);
    return () => clearInterval(latido);
  }, [settings, state]);

  // Y se dicen solo con Vibi en reposo. Cortarle una respuesta a mitad para
  // contarle a alguien que le ha llegado un WhatsApp es exactamente la razón
  // por la que la gente apaga estas cosas.
  useEffect(() => {
    if (state !== "sleeping" || diciendoAviso.current) return;
    const siguiente = avisosPendientes.current.shift();
    if (!siguiente) return;

    diciendoAviso.current = true;
    const parar = speakSpanish(siguiente, () => {
      diciendoAviso.current = false;
      // Sacude el efecto para vaciar la cola si quedaba más de uno.
      setAvisoDicho((contador) => contador + 1);
    });
    return () => {
      parar();
      diciendoAviso.current = false;
    };
  }, [state, avisoDicho]);

  // Deja las muletillas sintetizadas antes del primer turno. Sin esto la cara
  // se queda muda desde que dejas de hablar hasta que el modelo avisa de que va
  // a buscar algo, y eso son casi cinco segundos medidos: el aviso llega tarde
  // porque antes tiene que pensar. La muletilla suena al instante porque ya
  // está en memoria, y se pide por la vía del companion —su host, su token—,
  // que no es la de la consola.
  useEffect(() => {
    if (!settings) return;
    void prewarmAcknowledgements((texto) =>
      requestCompanionSpeech(settings, texto, new AbortController().signal),
    );
  }, [settings]);

  // La conversación dura lo que dura la sesión de voz: al cerrar la cara se
  // archiva en el servidor para que el próximo despertar empiece en blanco.
  const endSession = useCallback(async (options?: { yaArchivada?: boolean }) => {
    if (closingRef.current) return;
    const wasActive = activeRef.current;
    activeRef.current = false;
    captureRef.current?.cancel();
    captureRef.current = null;
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
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
    // Solo hay despedida que enseñar si de verdad hubo conversación: cuando la
    // ventana ya está escondida (Alt+F4, arranque en frío) esperar sería tiempo
    // muerto antes de reanudar la escucha.
    if (wasActive) {
      setSaliendo(true);
      await new Promise((listo) => setTimeout(listo, DESPEDIDA_MS));
      if (mountedRef.current) setSaliendo(false);
    }
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
    // Identifica el turno en el canal de eventos, igual que en la cara del
    // navegador: es lo que permite reconocer sus fragmentos según llegan.
    const turnId = `desktop-${crypto.randomUUID()}`;
    let stream: SpeechStream | null = null;

    try {
      const blob = await capture.stop();
      if (!blob.size) throw new Error("No he oído ninguna voz.");

      // El canal de locución se abre ANTES de pedir el turno, no después. Lo
      // que Vibi escribe justo antes de llamar a una herramienta ("ahora te
      // lo busco") existe para tapar el silencio que viene: dicho al final, ya
      // con el resultado en la mano, no tapa nada. Además ese texto ni siquiera
      // llega en la respuesta de /api/voz, que trae solo el bloque posterior a
      // la herramienta; el único sitio donde aparece es este canal.
      stream = createSpeechStream(
        () => {
          if (!mountedRef.current || speechRef.current !== stream) return;
          unsubscribeRef.current?.();
          unsubscribeRef.current = null;
          speechRef.current = null;
          if (activeRef.current) beginListeningRef.current();
        },
        {
          // Va delante en la cola: tapa el hueco hasta que el modelo dice algo.
          acknowledgement: takeAcknowledgement(),
          requestAudio: (text, signal) =>
            requestCompanionSpeech(currentSettings, text, signal),
        },
      );
      speechRef.current = stream;
      const activo = stream;

      let fronteras = 0;
      unsubscribeRef.current = client.getQueryCache().subscribe(() => {
        if (speechRef.current !== activo) return;
        const runtime = client.getQueryData<ChatRuntimeState | null>(
          chatRuntimeKey,
        );
        if (runtime?.turn_id !== turnId) return;
        if (runtime.text) setState("speaking");
        // Cerrar un bloque para usar una herramienta es la señal de que ese
        // texto ya está entero y se puede decir sin esperar al punto final.
        const boundary = runtime.boundaries > fronteras;
        fronteras = runtime.boundaries;
        activo.push(runtime.text, { boundary });
      });

      const result = await sendCompanionVoice(
        currentSettings,
        blob,
        filenameFor(blob),
        conversationId,
        controller.signal,
        turnId,
      );
      requestRef.current = null;
      if (!mountedRef.current || !activeRef.current) return;
      setHeard(result.transcripcion);
      if (result.via === "cerrar") {
        // La despedida ya archivó la conversación al procesar el audio.
        void endSession({ yaArchivada: true });
        return;
      }

      // La respuesta completa cierra el turno. Si los eventos no llegaron
      // —companion sin consola conectada, WebSocket caído— esto es también lo
      // que salva la locución entera.
      setState("speaking");
      stream.push(result.respuesta);
      stream.end();
    } catch (caught) {
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
      if (speechRef.current === stream) {
        stream?.cancel();
        speechRef.current = null;
      }
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
  }, [client, endSession]);
  sendCurrentRef.current = () => void sendCurrent();

  const beginListening = useCallback(async () => {
    if (!activeRef.current || !settingsRef.current || captureRef.current) return;
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
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
      listen("vibi://wake", wake),
      // Alt+F4 y cualquier otro cierre de ventana se resuelven en Rust: sin
      // este aviso la conversación seguiría viva en el próximo despertar.
      listen("vibi://end-session", () => endSessionRef.current()),
      listen<string>("vibi://listener-error", (event) => {
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

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Alt" && !e.repeat && !e.ctrlKey && !e.shiftKey && !e.metaKey) {
        if (!altTimerRef.current && !altWokenRef.current) {
          altTimerRef.current = setTimeout(() => {
            altWokenRef.current = true;
            wake();
          }, 400);
        }
      } else if (e.key !== "Alt") {
        if (altTimerRef.current) {
          clearTimeout(altTimerRef.current);
          altTimerRef.current = null;
        }
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.key === "Alt") {
        if (altTimerRef.current) {
          clearTimeout(altTimerRef.current);
          altTimerRef.current = null;
        }
        altWokenRef.current = false;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);

    return () => {
      cancelled = true;
      mountedRef.current = false;
      if (altTimerRef.current) {
        clearTimeout(altTimerRef.current);
        altTimerRef.current = null;
      }
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      unlisteners.forEach((unlisten) => unlisten());
      captureRef.current?.cancel();
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
      speechRef.current?.cancel();
      requestRef.current?.abort();
    };
  }, [wake]);

  // La cara no depende solo de la voz: mientras no haya conversación, lo que
  // pasa en el resto de Vibi es lo que tiene algo que contar. Va antes del
  // retorno del panel de vinculación porque un hook no puede quedar detrás de
  // un `return` condicional.
  const animo = useFaceMood(faceState(state), enConversacion(state));

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

  // Vinculado pero sin sesión de consola. Pasa con un companion de antes de que
  // la consola existiera, y a los treinta días, cuando el JWT caduca. La voz
  // sigue yendo —usa el token de nodo— así que el síntoma es silencioso: se
  // pierden las notificaciones y la cara deja de locutar sobre la marcha.
  if (!settings.userToken) {
    return (
      <ConsolaPanel
        nombre={settings.userName ?? ""}
        onConectado={(actualizado) => {
          applyCompanionSession(actualizado);
          settingsRef.current = actualizado;
          setSettings(actualizado);
          setError("");
        }}
      />
    );
  }

  const copyDeVoz =
    state === "opening" ||
    state === "listening" ||
    state === "thinking" ||
    state === "speaking" ||
    state === "closing" ||
    state === "error"
      ? stateCopy[state]
      : "";
  // Lo que cuenta el ánimo manda cuando la voz no tiene nada que decir: en
  // reposo el texto útil es «necesito tu permiso», no el vacío.
  const copy = animo.copy || copyDeVoz;

  return (
    <main
      className={[
        "companion-shell",
        `companion-${state}`,
        `cara-${animo.cara}`,
        saliendo ? "companion-saliendo" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="companion-drag" data-tauri-drag-region aria-hidden="true" />
      <button
        type="button"
        className="companion-face"
        onClick={() => void endSession()}
        aria-label="Cerrar la conversación con Vibi"
      >
        <span className="companion-halo" aria-hidden="true">
          <span className="halo-nucleo" />
          <span className="halo-anillo" />
          <span className="halo-aura" />
        </span>
        <VibiFace state={animo.cara} perfil="companion" senales={animo.senales} />
      </button>
      {/* Las `key` son lo que hace que cada frase entre en vez de aparecer de
          golpe: al cambiar el texto React remonta el nodo y la animación de
          entrada vuelve a empezar. */}
      <section className="companion-feedback" aria-live="polite">
        <p key={copy}>{copy}</p>
        {heard && state !== "error" && <span key={heard}>“{heard}”</span>}
        {error && <span key={error} className="companion-error">{error}</span>}
      </section>
      <CompanionConsolaBoton />
      {state !== "sleeping" && (
        <button type="button" className="companion-close" onClick={() => void endSession()}>
          Clic para terminar
        </button>
      )}
    </main>
  );
}

/**
 * Acceso a la consola desde la cara, con el número de cosas que esperan
 * decisión. Escucha los eventos del servidor para que el aviso salte solo:
 * si Vibi pide permiso mientras hablas, lo ves sin abrir nada.
 */
function CompanionConsolaBoton() {
  // Sin credencial de usuario no hay consola que consultar: un companion
  // vinculado antes de que existiera nunca llegó a pedirla. Eso no puede
  // resolverse en silencio —te dejaría esperando un permiso que nadie te va a
  // enseñar—, así que el botón lo dice y la consola te deja arreglarlo.
  const [conectada, setConectada] = useState(() =>
    Boolean(loadCompanionSettings()?.userToken),
  );
  const aprobaciones = useQuery<NodeOrder[]>({
    queryKey: nodeApprovalsKey,
    queryFn: fetchNodeApprovals,
    enabled: conectada,
  });
  const pendientes = aprobaciones.data?.length ?? 0;
  // Notificaciones que Vibi ha mirado por su cuenta mientras no estabas. No se
  // locutan: si algo merecía oírse, ella ya lo dijo con `avisos.decir`. Esto
  // solo señala que dejó algo escrito, para no tener que abrir el chat por si
  // acaso. Se cuentan aquí y no en la cara porque el pip ya vive en este botón.
  const [mirados, setMirados] = useState(0);

  useEffect(
    () =>
      suscribirEventos((evento) => {
        if (evento.tipo !== "avisos_deliberados") return;
        setMirados((cuantos) => cuantos + (evento.cuantos ?? 1));
      }),
    [],
  );

  useEffect(() => {
    if (!mirados) return;
    void notificar(
      mirados === 1
        ? "Vibi ha mirado una notificación"
        : `Vibi ha mirado ${mirados} notificaciones`,
      "Te ha dejado escrito lo que decidió.",
    );
  }, [mirados]);

  // La consola vive en otra ventana: cuando allí se mete la contraseña, esta
  // se entera al recuperar el foco y deja de dar la lata.
  useEffect(() => {
    const revisar = () =>
      setConectada(Boolean(loadCompanionSettings()?.userToken));
    window.addEventListener("focus", revisar);
    return () => window.removeEventListener("focus", revisar);
  }, []);

  useEffect(() => {
    if (!pendientes) return;
    void notificar(
      pendientes === 1
        ? "Vibi necesita tu permiso"
        : `${pendientes} órdenes esperan tu permiso`,
      "Ábrelo para ver el comando antes de decidir.",
    );
  }, [pendientes]);

  const aviso = !conectada || pendientes > 0 || mirados > 0;
  const señalados = pendientes + mirados;
  return (
    <button
      type="button"
      className={`companion-consola${aviso ? " con-avisos" : ""}`}
      onClick={() => {
        // Se apaga al abrir: lo que Vibi decidió se lee ahí dentro, y dejar el
        // número encendido después de haberlo visto lo vuelve ruido de fondo.
        setMirados(0);
        void invoke("open_panel");
      }}
      title={
        conectada
          ? "Permisos, bandeja y archivos"
          : "Falta conectar la consola: ábrela para hacerlo"
      }
    >
      <PanelRight size={14} aria-hidden />
      Consola
      {/* La `key` hace que el pip vuelva a saltar cuando sube el número, no
          solo la primera vez que aparece. */}
      {señalados > 0 && (
        <span key={señalados} className="companion-pip">
          {señalados}
        </span>
      )}
      {!conectada && <span className="companion-pip">!</span>}
    </button>
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
      <h1>Vibi</h1>
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

/**
 * Recupera la sesión de consola sin deshacer la vinculación de voz.
 *
 * Solo pide la contraseña: el servidor y el nombre del PC ya están guardados y
 * volver a preguntarlos daría a entender que hay que empezar de cero, cuando lo
 * que falta es únicamente el JWT.
 */
function ConsolaPanel({
  nombre,
  onConectado,
}: {
  nombre: string;
  onConectado: (settings: CompanionSettings) => void;
}) {
  const [name, setName] = useState(nombre);
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const actualizado = await connectCompanionConsole({ name, password });
      setPassword("");
      onConectado(actualizado);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="companion-setup">
      <div className="setup-sigil" aria-hidden="true">✦</div>
      <p className="setup-eyebrow">Reconectar la consola</p>
      <h1>Vibi</h1>
      <p className="setup-nota">
        Este PC sigue vinculado y la voz funciona. Lo que falta es la sesión de
        consola, que caduca cada treinta días: sin ella no te llegan las
        notificaciones ni la cara puede contarte lo que va haciendo.
      </p>
      <form onSubmit={submit}>
        <label>
          <span>Nombre</span>
          <input
            autoComplete="username"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </label>
        <label>
          <span>Contraseña</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error && <p className="setup-error">{error}</p>}
        <button disabled={pending}>
          {pending ? "Conectando…" : "Reconectar"}
        </button>
      </form>
    </main>
  );
}
