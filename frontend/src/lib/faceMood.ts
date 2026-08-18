import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { ChatRuntimeState, NodeOrder, ServerEvent } from "../types";
import { chatRuntimeKey } from "./conversation";
import type { FaceState } from "./face/estados";
import { SENALES_QUIETAS, type Senales } from "./face/modificadores";
import {
  estadoCanalActual,
  suscribirCanal,
  suscribirEventos,
  type EstadoCanal,
} from "./eventBus";
import { caraDeHerramienta } from "./faceTool";
import { nodeApprovalsKey } from "./nodeApprovals";

/**
 * Qué cara toca.
 *
 * Hasta ahora la cara solo sabía del ciclo de voz: escuchar, pensar, responder.
 * Todo lo demás que hace Vibi —ejecutar una herramienta, esperar un permiso,
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

/**
 * Lo que devuelve el hook: la cara y, aparte, las señales vivas del turno.
 *
 * Van separadas porque se deciden distinto. La cara es una elección —de todo lo
 * que pasa, esto es lo que toca contar—, y las señales son medidas que viajan
 * enteras hasta la escena para montarse encima del gesto que sea.
 */
export interface AnimoConSenales extends Animo {
  senales: Senales;
}

type Destello = { cara: FaceState; copy: string; hasta: number } | null;

/**
 * Decide la expresión a partir de todas las señales.
 *
 * El orden importa y es deliberado:
 *
 * 1. **Sin canal no hay nada que contar.** Si el servidor no está, cualquier
 *    otra cara sería mentira — incluida la de la herramienta, porque lo que
 *    sabemos del turno se quedó congelado en el último evento que llegó.
 * 2. **Estar trabajando gana a la voz.** Si está ejecutando algo, eso es lo que
 *    está pasando, le estés hablando o no. Solo cede cuando te escucha o te
 *    contesta, que entonces la voz manda.
 * 3. **Y hablar con ella gana al resto.** Si te está escuchando y llega un
 *    archivo, no se pone a mirar el archivo: sigue contigo. Interrumpir a quien
 *    te habla es justo lo que hace que un asistente resulte irritante.
 * 4. Después los destellos, que son noticias frescas.
 * 5. Y por último lo que espera de ti, que puede aguantar.
 */
export function decidirAnimo(entrada: {
  voz: FaceState;
  enConversacion: boolean;
  canal: EstadoCanal;
  pendientes: number;
  fase: ChatRuntimeState["fase"] | null;
  herramienta: string;
  destello: Destello;
  ahora: number;
}): Animo {
  const { voz, enConversacion, canal, pendientes, fase, herramienta, destello, ahora } =
    entrada;

  if (canal === "caido") {
    return { cara: "offline", copy: "Sin conexión con el servidor" };
  }

  // Trabajar sube por encima de la conversación, y no es un detalle: antes esto
  // vivía dentro de `enConversacion`, así que en la PWA —donde no hay sesión de
  // voz abierta— ninguna herramienta se veía nunca. `idle` cuenta tanto como
  // `thinking` por lo mismo: en la web el turno corre sin que la voz se entere.
  if (fase === "herramienta" && (voz === "thinking" || voz === "idle")) {
    return caraDeHerramienta(herramienta);
  }

  // El arranque del turno tampoco tenía cara: se veía la de pensar aunque
  // todavía no estuviera pensando nada, solo despertando el motor.
  if (fase === "arranque" && (voz === "thinking" || voz === "idle")) {
    return { cara: "arranque", copy: "" };
  }

  if (enConversacion) {
    return { cara: voz, copy: "" };
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
): AnimoConSenales {
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

  // Las señales vivas se acumulan en refs y se publican a intervalos. Meterlas
  // en el estado de React según llegan haría un render por cada `delta`, que en
  // un turno largo son miles; a cinco por segundo la bola late y se apaga igual
  // de bien y no se nota en el perfilador.
  const cadenciaRef = useRef(crearCadencia());
  const pongRef = useRef(Date.now());
  const corteRef = useRef(0);
  const [senales, setSenales] = useState<Senales>(SENALES_QUIETAS);

  useEffect(
    () =>
      suscribirEventos((event) => {
        if (event.tipo === "pong") {
          pongRef.current = Date.now();
          return;
        }
        if (event.tipo !== "chat_runtime") return;
        if (event.event === "delta") {
          cadenciaRef.current.anotar(Date.now() / 1000);
          if (event.boundary) corteRef.current = Date.now();
        }
      }),
    [],
  );

  useEffect(() => {
    const publicar = () => {
      const ahora = Date.now();
      setSenales((previo) => ({
        ...previo,
        cadencia: cadenciaRef.current.porSegundo(ahora / 1000),
        retrasoCanal: ahora - pongRef.current,
        corte: corteRef.current,
      }));
    };
    const temporizador = window.setInterval(publicar, 200);
    return () => window.clearInterval(temporizador);
  }, []);

  // La cola de permisos y la fase del turno viven en la caché de consultas, que
  // cambia sin que React lo sepa: hay que mirarla por suscripción.
  useEffect(() => {
    const cache = client.getQueryCache();
    return cache.subscribe(() => forzar((valor) => valor + 1));
  }, [client]);

  const pendientes =
    client.getQueryData<NodeOrder[]>(nodeApprovalsKey)?.length ?? 0;
  const runtime = client.getQueryData<ChatRuntimeState | null>(chatRuntimeKey);

  return {
    ...decidirAnimo({
      voz,
      enConversacion,
      canal,
      pendientes,
      fase: runtime?.fase ?? null,
      herramienta: runtime?.herramienta ?? "",
      destello,
      ahora: Date.now(),
    }),
    senales: { ...senales, pasos: runtime?.boundaries ?? 0, pendientes,
      remoto: senalesDe({ runtime }).remoto },
  };
}

/**
 * Cuántos `delta` por segundo están llegando.
 *
 * Sirve para que el latido de hablar lo marque el caudal real de tokens en vez
 * de un seno inventado. Lo importante es que **se olvide**: si el modelo se
 * atasca, la cadencia cae a cero y la cara se queda quieta, y esa quietud es
 * justo la información que hace falta.
 */
export function crearCadencia(ventana = 1.5) {
  let marcas: number[] = [];
  return {
    anotar(ahora: number) {
      marcas.push(ahora);
    },
    porSegundo(ahora: number): number {
      const desde = ahora - ventana;
      marcas = marcas.filter((marca) => marca >= desde);
      return marcas.length / ventana;
    },
  };
}

/**
 * Qué equipo está ejecutando, o `null` si es este.
 *
 * Se deduce del nombre de la herramienta porque es lo único que llega: los
 * verbos de la malla van con `pc_` delante o hablan de `devices`. No sabemos el
 * nombre real del equipo, así que se etiqueta con lo que sí sabemos —que pasa
 * fuera—, que es lo que la cara necesita contar.
 */
function equipoDe(herramienta: string): string | null {
  const clave = herramienta.toLowerCase();
  if (clave.startsWith("pc_") || clave.includes("devices")) return "tu equipo";
  return null;
}

/**
 * Reúne las señales vivas del turno.
 *
 * Las seis salen de cosas que ya llegan al frontend y que hasta ahora se
 * descartaban: el contador de bloques cerrados, el caudal de `delta`, el pulso
 * del canal y el nombre crudo de la herramienta.
 */
export function senalesDe(entrada: {
  runtime: ChatRuntimeState | null | undefined;
  pendientes?: number;
  cadencia?: number;
  retrasoCanal?: number;
  corte?: number;
}): Senales {
  const { runtime, pendientes = 0, cadencia = 0, retrasoCanal = 0, corte = 0 } = entrada;
  return {
    ...SENALES_QUIETAS,
    pasos: runtime?.boundaries ?? 0,
    cadencia,
    retrasoCanal,
    remoto: equipoDe(runtime?.herramienta ?? ""),
    pendientes,
    corte,
  };
}
