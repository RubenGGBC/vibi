import { useEffect, useRef, useState, type FormEvent } from "react";

import { ApiError, apiFetch } from "../lib/api";
import { forgetCompanionUserToken } from "../lib/companionApi";
import type { MessageResponse } from "../types";

interface Turno {
  mio: boolean;
  texto: string;
}

/** Lo que se enseña de cada respuesta, que no siempre trae texto. */
const leerRespuesta = (respuesta: MessageResponse): string => {
  if (respuesta.via === "agentica") return "Me pongo con ello.";
  return respuesta.respuesta || "Hecho.";
};

/**
 * Chat de texto pegado a la mascota, para lo que no quieres decir en voz alta.
 *
 * Vive aparte de la consola y solo ensancha la ventana flotante mientras está
 * abierto. La voz sigue exactamente donde estaba —esto no abre sesión de voz
 * ni toca el micrófono—, así que se puede escribir con alguien delante sin que
 * Vibi se ponga a hablar.
 */
export function MascotaChat({
  onCerrar,
  onIniciarSesion,
}: {
  onCerrar: () => void;
  onIniciarSesion?: () => void;
}) {
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState("");
  const [caducada, setCaducada] = useState(false);
  const campoRef = useRef<HTMLInputElement | null>(null);
  const hiloRef = useRef<HTMLDivElement | null>(null);

  // Abrir el bocadillo es querer escribir. El campo queda listo en el mismo
  // clic con el que se despierta a Vibi.
  useEffect(() => campoRef.current?.focus(), []);

  useEffect(() => {
    const cerrarConEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCerrar();
    };
    window.addEventListener("keydown", cerrarConEscape);
    return () => window.removeEventListener("keydown", cerrarConEscape);
  }, [onCerrar]);

  useEffect(() => {
    const hilo = hiloRef.current;
    if (hilo) hilo.scrollTop = hilo.scrollHeight;
  }, [turnos, enviando]);

  const enviar = async (event: FormEvent) => {
    event.preventDefault();
    const limpio = texto.trim();
    // Dos guardas para dos accidentes distintos: el Enter de más sobre un campo
    // vacío, y el segundo envío mientras el turno todavía está en vuelo. Este
    // último llegaba a mandar el mismo encargo dos veces.
    if (!limpio || enviando) return;

    setTexto("");
    setError("");
    setTurnos((previos) => [...previos, { mio: true, texto: limpio }]);
    setEnviando(true);
    try {
      const respuesta = await apiFetch<MessageResponse>("/api/mensaje", {
        method: "POST",
        body: JSON.stringify({
          texto: limpio,
          client_ref: crypto.randomUUID(),
        }),
      });
      setTurnos((previos) => [
        ...previos,
        { mio: false, texto: leerRespuesta(respuesta) },
      ]);
    } catch (caught) {
      // El JWT dura treinta días y caduca en silencio. Sin este caso aparte, el
      // chat enseñaba un «La petición falló (401)» que no dice qué hacer, y la
      // tentación era reintentar con el token de nodo: ese vive en esta máquina,
      // solo abre la voz, y darle la API entera haría que quien lo robara
      // pudiera aprobar las órdenes que él mismo pide.
      if (caught instanceof ApiError && caught.status === 401) {
        setCaducada(true);
      } else {
        setError(
          caught instanceof Error
            ? caught.message
            : "No he podido mandarlo. Comprueba que Vibi siga en pie.",
        );
      }
    } finally {
      setEnviando(false);
    }
  };

  return (
    <section className="mascota-chat" role="dialog" aria-label="Chat con Vibi">
      <header className="mascota-chat-barra">
        <span><i aria-hidden="true" /> Pregunta a Vibi</span>
        <button type="button" onClick={onCerrar} aria-label="Cerrar el chat">
          ×
        </button>
      </header>

      <div className="mascota-chat-hilo" ref={hiloRef} aria-live="polite">
        {turnos.length === 0 && !enviando && !error && !caducada && (
          <p className="turno-suyo turno-bienvenida">
            ¿Qué quieres saber?
          </p>
        )}
        {turnos.map((turno, indice) => (
          <p
            key={`${indice}-${turno.texto}`}
            className={turno.mio ? "turno-mio" : "turno-suyo"}
          >
            {turno.texto}
          </p>
        ))}
        {enviando && <p className="turno-esperando">Pensando…</p>}
        {error && <p className="mascota-chat-error">{error}</p>}
        {caducada && (
          <div className="mascota-chat-caducada">
            <p>Tu sesión ha caducado. Vuelve a entrar para seguir escribiendo.</p>
            <button
              type="button"
              onClick={() => {
                forgetCompanionUserToken();
                onIniciarSesion?.();
              }}
            >
              Iniciar sesión
            </button>
          </div>
        )}
      </div>

      <form className="mascota-chat-campo" onSubmit={enviar}>
        <input
          ref={campoRef}
          aria-label="Escribe a Vibi"
          value={texto}
          onChange={(event) => setTexto(event.target.value)}
          placeholder="Escribe una pregunta…"
        />
        <button type="submit" disabled={enviando || !texto.trim()} aria-label="Enviar">
          Enviar
        </button>
      </form>
    </section>
  );
}
