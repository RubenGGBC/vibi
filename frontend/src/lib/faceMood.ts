import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { ChatRuntimeState, NodeOrder, ServerEvent } from "../types";
import { chatRuntimeKey } from "./conversation";
import type { FaceState } from "./face3d";
import {
  estadoCanalActual,
  suscribirCanal,
  suscribirEventos,
  type EstadoCanal,
} from "./eventBus";
import { nodeApprovalsKey } from "./nodeApprovals";

/**
 * Qué cara toca.
 *
 * Hasta ahora la cara solo sabía del ciclo de voz: escuchar, pensar, responder.
 * Todo lo demás que hace Morgana —ejecutar una herramienta, esperar un permiso,
 * recibir un archivo del móvil, quedarse sin servidor— pasaba sin que se le
 * moviera un músculo. Este módulo es el que traduce esas señales a expresiones.
 *
 * Hay dos clases de señal y se tratan distinto:
 *
 * - Las **persistentes** son un estado del mundo: el canal está caído, hay tres
 *   órdenes esperando permiso. Duran lo que dure la condición.
 * - Los **destellos** son cosas que pasan y se acaban: ha llegado un archivo,
 *   una tarea ha fallado. Duran unos segundos y se apagan solos, porque una
 *   cara que se queda con el gesto de la sorpresa parece rota.
 */

/** Cuánto se queda puesto un destello antes de volver a lo de siempre. */
const DESTELLO_MS = 2600;

export interface Animo {
  /** La cara a poner. */
  cara: FaceState;
  /** Qué contar debajo, o cadena vacía si manda el texto de la conversación. */
  copy: string;
}

type Destello = { cara: FaceState; copy: string; hasta: number } | null;

/**
 * Decide la expresión a partir de todas las señales.
 *
 * El orden importa y es deliberado:
 *
 * 1. **Estar hablando con ella gana a todo.** Si te está escuchando y llega un
 *    archivo, no se pone a mirar el archivo: sigue contigo. Interrumpir a quien
 *    te habla es justo lo que hace que un asistente resulte irritante.
 * 2. **Sin canal no hay nada que contar.** Si el servidor no está, cualquier
 *    otra cara sería mentira.
 * 3. Después los destellos, que son noticias frescas.
 * 4. Y por último lo que espera de ti, que puede aguantar.
 */
export function decidirAnimo(entrada: {
  voz: FaceState;
  enConversacion: boolean;
  canal: EstadoCanal;
  pendientes: number;
  fase: ChatRuntimeState["fase"] | null;
  destello: Destello;
  ahora: number;
}): Animo {
  const { voz, enConversacion, canal, pendientes, fase, destello, ahora } = entrada;

  if (enConversacion) {
    // Pensando es esperar; trabajando es tener las manos ocupadas. Antes las
    // dos cosas eran la misma cara y un turno con herramientas se veía igual de
    // quieto que uno que no hacía nada.
    if (voz === "thinking" && fase === "herramienta") {
      return { cara: "working", copy: "Trabajando en ello" };
    }
    return { cara: voz, copy: "" };
  }

  if (canal === "caido") {
    return { cara: "offline", copy: "Sin conexión con el servidor" };
  }

  if (destello && destello.hasta > ahora) {
    return { cara: destello.cara, copy: destello.copy };
  }

  if (pendientes > 0) {
    return {
      cara: "waiting",
      copy:
        pendientes === 1
          ? "Necesito tu permiso"
          : `${pendientes} órdenes esperan permiso`,
    };
  }

  return { cara: voz, copy: "" };
}

/**
 * Traduce un evento del servidor a un destello, o a nada.
 *
 * Solo se queda con lo que merece un gesto. Un `chat_runtime` llega decenas de
 * veces por turno y la cara ya lo cuenta por otra vía; ponerle un destello
 * sería un tic constante.
 */
export function destelloDe(event: ServerEvent): Omit<Destello & object, "hasta"> | null {
  if (event.tipo === "transferencia") {
    // Una transferencia emite en cada paso. Solo merecen gesto los dos finales:
    // lo de en medio sería la cara cambiando cada pocos kilobytes.
    if (event.transferencia.estado === "error") {
      return { cara: "alert", copy: "Una transferencia ha fallado" };
    }
    if (event.transferencia.estado === "en_servidor") {
      return { cara: "pleased", copy: `Ha llegado ${event.transferencia.nombre}` };
    }
    return null;
  }
  if (event.tipo === "tarea_actualizada") {
    if (event.task.estado === "error" || event.task.estado === "rechazada") {
      return { cara: "alert", copy: "Una tarea ha terminado mal" };
    }
    if (event.task.estado === "completada") {
      return { cara: "pleased", copy: "Tarea terminada" };
    }
    if (event.task.estado === "esperando_aprobacion") {
      return { cara: "waiting", copy: "Una tarea espera tu aprobación" };
    }
    return null;
  }
  if (event.tipo === "nodo_presencia") {
    return event.nodo.online
      ? {
          cara: "pleased",
          copy: `${event.nodo.nombre ?? "Otro equipo"} se ha conectado`,
        }
      : {
          cara: "alert",
          copy: `${event.nodo.nombre ?? "Un equipo"} se ha desconectado`,
        };
  }
  if (event.tipo === "notificacion") {
    return { cara: "waiting", copy: event.texto };
  }
  return null;
}

/**
 * El enganche con React: escucha el canal, la cola de permisos y la fase del
 * turno, y devuelve la cara que toca.
 *
 * `enConversacion` lo pasa quien lo usa porque solo el companion sabe si su
 * sesión de voz está viva; desde aquí no se puede adivinar.
 */
export function useFaceMood(
  voz: FaceState,
  enConversacion: boolean,
): Animo {
  const client = useQueryClient();
  const [canal, setCanal] = useState<EstadoCanal>(estadoCanalActual);
  const [destello, setDestello] = useState<Destello>(null);
  const [, forzar] = useState(0);

  useEffect(() => suscribirCanal(setCanal), []);

  useEffect(
    () =>
      suscribirEventos((event) => {
        const nuevo = destelloDe(event);
        if (!nuevo) return;
        setDestello({ ...nuevo, hasta: Date.now() + DESTELLO_MS });
      }),
    [],
  );

  // Un destello se apaga solo aunque no llegue ningún evento más: sin este
  // temporizador la cara se quedaría contenta para siempre tras un archivo.
  useEffect(() => {
    if (!destello) return;
    const restante = destello.hasta - Date.now();
    if (restante <= 0) {
      setDestello(null);
      return;
    }
    const temporizador = window.setTimeout(() => setDestello(null), restante);
    return () => window.clearTimeout(temporizador);
  }, [destello]);

  // La cola de permisos y la fase del turno viven en la caché de consultas, que
  // cambia sin que React lo sepa: hay que mirarla por suscripción.
  useEffect(() => {
    const cache = client.getQueryCache();
    return cache.subscribe(() => forzar((valor) => valor + 1));
  }, [client]);

  const pendientes =
    client.getQueryData<NodeOrder[]>(nodeApprovalsKey)?.length ?? 0;
  const fase =
    client.getQueryData<ChatRuntimeState | null>(chatRuntimeKey)?.fase ?? null;

  return decidirAnimo({
    voz,
    enConversacion,
    canal,
    pendientes,
    fase,
    destello,
    ahora: Date.now(),
  });
}
