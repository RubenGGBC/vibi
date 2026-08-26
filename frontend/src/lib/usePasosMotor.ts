import { useEffect, useState } from "react";

import { suscribirEventos } from "./eventBus";
import type { PasoMotor } from "./pasosMotor";

/**
 * Los pasos que va dando el motor, escuchados del canal.
 *
 * Vivía dentro de `ProcesoMotor`, que es la ventana de escritorio de «qué está
 * haciendo». Sale aquí porque la página **Ahora** cuenta lo mismo y no tiene
 * sentido que exista dos veces: lo que cambia entre las dos es la pinta, no el
 * mecanismo.
 *
 * **No abre WebSocket propio, y eso importa.** La primera versión de aquella
 * ventana sí lo hacía y no mandaba el frame de autenticación, así que el
 * servidor la cerraba con 4401, ella reconectaba a los dos segundos y vuelta a
 * empezar: un bucle infinito que saturaba el canal por el que va la voz. Aquí
 * solo se escucha lo que reparte `useEvents`, que ya sabe autenticarse.
 */

/** Un tope, que esto puede estar abierto todo el día. */
const MAXIMO = 200;

export function usePasosMotor(limite = MAXIMO): PasoMotor[] {
  const [pasos, setPasos] = useState<PasoMotor[]>([]);

  useEffect(
    () =>
      suscribirEventos((evento) => {
        const dato = evento as unknown as Record<string, unknown>;
        if (dato.tipo !== "chat_runtime" || dato.event !== "engine_step") return;

        const entrante: PasoMotor = {
          turno: String(dato.turn_id ?? ""),
          tipo: String(dato.paso ?? ""),
          estado: String(dato.estado ?? ""),
          detalle: String(dato.detalle ?? ""),
          momento: Date.now(),
        };
        setPasos((previos) => {
          // El mismo paso vuelve al cambiar de estado: se actualiza en su sitio
          // en vez de apilarse, o la lista sería ilegible.
          const encontrado = previos.findIndex(
            (p) =>
              p.turno === entrante.turno &&
              p.tipo === entrante.tipo &&
              p.detalle === entrante.detalle,
          );
          if (encontrado >= 0) {
            const copia = [...previos];
            copia[encontrado] = { ...copia[encontrado], estado: entrante.estado };
            return copia;
          }
          return [...previos, entrante].slice(-limite);
        });
      }),
    [limite],
  );

  return pasos;
}

/** Agrupados por turno, que es la unidad que le importa a quien mira. */
export function porTurno(pasos: PasoMotor[]): Map<string, PasoMotor[]> {
  return pasos.reduce<Map<string, PasoMotor[]>>((mapa, paso) => {
    const lista = mapa.get(paso.turno) ?? [];
    lista.push(paso);
    mapa.set(paso.turno, lista);
    return mapa;
  }, new Map());
}

/** Un paso todavía en marcha. Los motores lo dicen con estas dos palabras. */
export function enCurso(paso: PasoMotor): boolean {
  return paso.estado.includes("RUNNING") || paso.estado.includes("PENDING");
}
