import { useQuery } from "@tanstack/react-query";
import { Eye, Monitor } from "lucide-react";
import { useEffect, useState } from "react";

import { AprobacionesPanel } from "../components/AprobacionesPanel";
import { apiFetch } from "../lib/api";
import { chatRuntimeKey, conversationKey } from "../lib/conversation";
import { suscribirEventos } from "../lib/eventBus";
import { caraDeHerramienta } from "../lib/faceTool";
import { desdeCuando, fetchNodos, nodosKey, ordenarNodos } from "../lib/nodos";
import { nombreLegible, resumirPaso } from "../lib/pasosMotor";
import { enCurso, usePasosMotor } from "../lib/usePasosMotor";
import type {
  ChatRuntimeState,
  ConversationState,
  NodeDevice,
} from "../types";

/**
 * Lo que está pasando, entero y en un solo sitio.
 *
 * Un turno se contaba en cuatro superficies y en ninguna completo: los pasos en
 * una ventana de escritorio aparte, la tarea en la bandeja, los archivos en
 * otra ruta y el rastro en Actividad. `turn_id` existía en el servidor y no
 * agrupaba nada en el cliente. Esta página es ese turno como un objeto.
 *
 * No es para actuar: aquí solo se mira. Lo único que se decide es lo que no
 * puede esperar, y por eso los permisos van arriba de la columna de al lado.
 */

const FASES: Record<ChatRuntimeState["fase"], string> = {
  arranque: "Despertando el motor",
  herramienta: "Usando una herramienta",
  redactando: "Redactando la respuesta",
};

export function AhoraPage() {
  const pasos = usePasosMotor();

  // Mismo patrón que `ChatPanel`: el runtime lo escribe `useEvents` en la
  // caché, así que aquí solo se observa. Sin `queryFn` de verdad, que no hay
  // endpoint — y sin `enabled` se pisaría el turno vivo al montar la página.
  const runtime = useQuery<ChatRuntimeState | null>({
    queryKey: chatRuntimeKey,
    queryFn: async () => null,
    enabled: false,
  });

  const conversacion = useQuery<ConversationState>({
    queryKey: conversationKey,
    queryFn: () =>
      apiFetch<ConversationState>("/api/conversations/active/messages?limit=50"),
  });

  const nodos = useQuery<NodeDevice[]>({ queryKey: nodosKey, queryFn: fetchNodos });

  // De qué está pendiente, si es que lo está. Llega por el canal y no tiene
  // endpoint: `app/vigilancias.py` no expone ninguno todavía.
  const [vigilando, setVigilando] = useState("");
  useEffect(
    () =>
      suscribirEventos((evento) => {
        if (evento.tipo !== "vigilancia") return;
        setVigilando(evento.activa ? evento.que_espero : "");
      }),
    [],
  );

  const turno = runtime.data ?? null;
  // Lo que pediste. El runtime no lo trae, así que sale del último mensaje tuyo
  // de la conversación activa, que es de donde salió el turno.
  const loQuePediste = [...(conversacion.data?.messages ?? [])]
    .reverse()
    .find((m) => m.role === "user")?.content;

  const herramienta = turno?.herramienta
    ? caraDeHerramienta(turno.herramienta)
    : null;

  return (
    <div className="ahora-page">
      <section className="ahora-turno">
        {turno ? (
          <>
            <header className="ahora-cabecera">
              <p className="ahora-fichas">
                <span className="ahora-ficha ahora-ficha-via">
                  {herramienta?.copy ?? FASES[turno.fase]}
                </span>
                {turno.boundaries > 0 && (
                  <span className="ahora-ficha">Paso {turno.boundaries}</span>
                )}
                <span className="ahora-turno-id">turno {turno.turn_id.slice(0, 8)}</span>
              </p>
              <h1>{loQuePediste || turno.label || "Un turno en marcha"}</h1>
              {turno.label && loQuePediste && (
                <p className="ahora-label">{turno.label}</p>
              )}
            </header>

            <div className="ahora-pasos">
              <p className="ahora-titulillo">Lo que va haciendo</p>
              {pasos.length === 0 ? (
                <p className="ahora-vacio-menor">
                  Todavía no ha dado ningún paso con nombre.
                </p>
              ) : (
                <ul>
                  {pasos
                    .filter((p) => p.turno === turno.turn_id || !p.turno)
                    .slice(-14)
                    .map((paso, i) => (
                      <li key={`${paso.tipo}-${paso.detalle}-${i}`} data-curso={enCurso(paso)}>
                        <i aria-hidden />
                        <b>{nombreLegible(paso.tipo)}</b>
                        {paso.detalle && <code>{resumirPaso(paso)}</code>}
                      </li>
                    ))}
                </ul>
              )}
            </div>

            {turno.text && (
              <div className="ahora-respuesta">
                <p className="ahora-titulillo">Lo que va diciendo</p>
                <p>{turno.text}</p>
              </div>
            )}
          </>
        ) : (
          <div className="ahora-vacio">
            <h1>Ahora mismo, nada</h1>
            <p>
              Cuando le pidas algo —por voz, desde el Hilo o desde Telegram—
              aquí verás el turno entero: en qué anda, qué herramienta usa, en
              qué equipo y qué va dejando.
            </p>
          </div>
        )}
      </section>

      <aside className="ahora-lado">
        {/* Lo único que no puede esperar, arriba del todo y siempre en el mismo
            sitio. Antes esto vivía en tres superficies distintas. */}
        <AprobacionesPanel />

        <section className="ahora-caja">
          <p className="ahora-titulillo">
            <Eye size={13} aria-hidden /> Vigilando por ti
          </p>
          {vigilando ? (
            <p className="ahora-vigilancia">«{vigilando}»</p>
          ) : (
            <p className="ahora-vacio-menor">
              Nada en stand-by. Pídeselo hablando: «avísame cuando acabe el
              build».
            </p>
          )}
        </section>

        <section className="ahora-caja">
          <p className="ahora-titulillo">
            <Monitor size={13} aria-hidden /> Tus equipos
          </p>
          <ul className="ahora-equipos">
            {ordenarNodos(nodos.data ?? []).map((nodo) => (
              <li key={nodo.id}>
                <i data-online={nodo.conectado} aria-hidden />
                <b>{nodo.nombre}</b>
                <span>
                  {nodo.conectado ? "conectado" : desdeCuando(nodo.last_seen)}
                </span>
              </li>
            ))}
            {!nodos.data?.length && (
              <li className="ahora-vacio-menor">Ningún equipo vinculado.</li>
            )}
          </ul>
        </section>
      </aside>
    </div>
  );
}
