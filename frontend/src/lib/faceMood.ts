import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { ChatRuntimeState, NodeOrder, ServerEvent } from "../types";
import { chatRuntimeKey } from "./conversation";
import type { FaceState } from "./face/estados";
import { MAX_RETRASO, SENALES_QUIETAS, type Senales } from "./face/modificadores";
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
  pendienteDe?: string;
  /** Alguna de las órdenes que esperan viene marcada de riesgo alto. */
  riesgoAlto?: boolean;
  /** Hay un turno en marcha ahora mismo. */
  turnoVivo?: boolean;
}): Animo {
  const {
    voz,
    enConversacion,
    canal,
    pendientes,
    fase,
    herramienta,
    destello,
    ahora,
    pendienteDe = "",
    riesgoAlto = false,
    turnoVivo = false,
  } = entrada;

  if (canal === "caido") {
    // Caerse en reposo y caerse con un turno a medias no son la misma noticia.
    // `offline` es encogerse a dormir, y eso está bien cuando no pasaba nada;
    // si había trabajo en marcha, lo que hay es un agujero: seguimos sin saber
    // en qué quedó, y la cara lo dice en vez de fingir que se echó la siesta.
    return turnoVivo
      ? { cara: "perdida", copy: "Se ha cortado con el turno a medias" }
      : { cara: "offline", copy: "Sin conexión con el servidor" };
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
    // El `riesgo` lo clasifica el servidor al crear la orden, así que aquí no
    // hay que adivinar nada leyendo comandos. Poner la misma cara a un `ls` que
    // a un `rm -rf` tiraba lo único que separa una decisión de un trámite.
    if (riesgoAlto) {
      return {
        cara: "recelo",
        copy:
          pendientes === 1
            ? "Esto no lo hago sin que lo mires"
            : `${pendientes} órdenes, y una es delicada`,
      };
    }
    return {
      cara: "waiting",
      copy:
        pendientes === 1
          ? "Necesito tu permiso"
          : `${pendientes} órdenes esperan permiso`,
    };
  }

  // El stand-by va por debajo del permiso y por encima del reposo. Por debajo
  // porque una orden esperando tu visto bueno es más urgente que estar mirando
  // algo; por encima porque «pendiente de la instalación» dice bastante más
  // que una cara en reposo, que es lo que se veía antes.
  if (pendienteDe) {
    return { cara: "vigilando", copy: `Pendiente de ${pendienteDe}` };
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
    // Reventar y que le digas que no son dos finales distintos, y hasta ahora
    // los dos ponían `alert`. El primero necesita que lo mires; el segundo es
    // una decisión tuya que ella acata, y no tiene por qué alarmar a nadie.
    if (event.task.estado === "error") {
      return { cara: "fallo", copy: "Una tarea ha reventado" };
    }
    if (event.task.estado === "rechazada") {
      return { cara: "denegada", copy: "Tarea descartada" };
    }
    // Un encargo agéntico terminado es la noticia larga: `logro`. El guiño de
    // `pleased` se queda para los acuses cortos, como un archivo que llega.
    if (event.task.estado === "completada") {
      return { cara: "logro", copy: "Tarea terminada" };
    }
    if (event.task.estado === "esperando_aprobacion") {
      return { cara: "waiting", copy: "Una tarea espera tu aprobación" };
    }
    return null;
  }
  if (event.tipo === "nodo_orden_resuelta") {
    // Solo el rechazo merece gesto: aprobar una orden ya se ve porque la cara
    // pasa a la de trabajar, y decir dos cosas del mismo clic sería un tic.
    if (event.orden.aprobacion === "rechazada") {
      return { cara: "denegada", copy: "Vale, la dejo" };
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
/**
 * Cuánto tiene que moverse el retraso del canal para que se vea. En ms.
 *
 * El desvanecido de la bola va de 0 a MAX_RETRASO, así que un cuarto de
 * segundo es una veinticuatroava parte del recorrido: por debajo de eso no hay
 * nada que enseñar, solo un número distinto que obliga a renderizar.
 */
const ESCALON_RETRASO = 250;

/**
 * El retraso del canal redondeado a lo que la cara llega a distinguir.
 *
 * Se publicaba crudo cinco veces por segundo, y como nunca daba dos veces el
 * mismo número, React volvía a renderizar la cara siempre. Lo caro no era el
 * render en sí, sino que ocurría eternamente y sin que cambiara nada.
 *
 * Satura en MAX_RETRASO porque `ajustesDe` acota ahí: por encima, todos los
 * valores pintan la misma bola apagada. Con el pong cada 30 s eso son 24 de
 * cada 30 segundos en los que ahora no se publica nada.
 */
export function retrasoVisible(ms: number): number {
  const acotado = Math.min(Math.max(ms, 0), MAX_RETRASO);
  return Math.round(acotado / ESCALON_RETRASO) * ESCALON_RETRASO;
}

export function useFaceMood(
  voz: FaceState,
  enConversacion: boolean,
): AnimoConSenales {
  const client = useQueryClient();
  const [canal, setCanal] = useState<EstadoCanal>(estadoCanalActual);
  const [destello, setDestello] = useState<Destello>(null);
  const [, forzar] = useState(0);

  useEffect(() => suscribirCanal(setCanal), []);

  // De qué está pendiente, si es que lo está. Vive aquí y no en el companion
  // porque el stand-by no es una pata de la máquina de estados de la voz: es
  // un modificador del reposo. Así hablarle no lo cancela —vuelve sola al
  // terminar el turno— y la cara de la PWA se entera igual, gratis.
  const [pendienteDe, setPendienteDe] = useState("");

  useEffect(
    () =>
      suscribirEventos((event) => {
        if (event.tipo !== "vigilancia") return;
        setPendienteDe(event.activa ? event.que_espero : "");
      }),
    [],
  );

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
      setSenales((previo) => {
        const cadencia = cadenciaRef.current.porSegundo(ahora / 1000);
        const retrasoCanal = retrasoVisible(ahora - pongRef.current);
        const corte = corteRef.current;
        // Devolver el mismo objeto es lo que corta el render: React compara
        // por identidad, y en reposo las tres señales se quedan quietas. Antes
        // se construía uno nuevo siempre, así que la cara se rerenderizaba
        // cinco veces por segundo para pintar exactamente lo mismo.
        if (
          previo.cadencia === cadencia &&
          previo.retrasoCanal === retrasoCanal &&
          previo.corte === corte
        ) {
          return previo;
        }
        return { ...previo, cadencia, retrasoCanal, corte };
      });
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

  const aprobaciones = client.getQueryData<NodeOrder[]>(nodeApprovalsKey);
  const pendientes = aprobaciones?.length ?? 0;
  // El servidor marca el riesgo al crear la orden; aquí solo se mira si alguna
  // de las que esperan es de las gordas.
  const riesgoAlto = aprobaciones?.some((orden) => orden.riesgo === "alto") ?? false;
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
      pendienteDe,
      riesgoAlto,
      // `useEvents` pone el runtime a null en cuanto llega `finished`, así que
      // que exista es exactamente «hay un turno en marcha».
      turnoVivo: runtime != null,
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
