import { useEffect, useRef, useState } from "react";

import { suscribirCanal, suscribirEventos, type EstadoCanal } from "../lib/eventBus";
import { nombreLegible, resumirPaso, type PasoMotor } from "../lib/pasosMotor";
import { useEvents } from "../lib/useEvents";

/**
 * Lo que Vibi está haciendo ahora mismo, paso a paso.
 *
 * Existe porque «pensando…» no explica nada: cuando un turno tarda un minuto,
 * lo único que resuelve la duda es ver que ha lanzado cinco búsquedas, o que
 * lleva veinte segundos en un comando. Es para mirar por encima del hombro, no
 * para actuar — no hay un solo botón que cambie nada.
 *
 * **No abre su propio WebSocket, y eso importa.** La primera versión sí lo
 * hacía y no mandaba el frame de autenticación, así que el servidor la cerraba
 * con 4401, ella reconectaba a los dos segundos y vuelta a empezar: un bucle
 * infinito de conexiones que saturaba el canal por el que va la voz. Y como
 * esta ventana nace oculta, el bucle corría sin que nadie viera nada.
 * `useEvents` ya sabe autenticarse, reintentar con espera creciente y callarse
 * cuando no hay sesión; aquí solo hay que escuchar lo que reparte.
 */
export function ProcesoMotor() {
  const [pasos, setPasos] = useState<PasoMotor[]>([]);
  const [canal, setCanal] = useState<EstadoCanal>("conectando");
  const fondo = useRef<HTMLDivElement>(null);

  useEvents();

  useEffect(() => suscribirCanal(setCanal), []);

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
          // Un tope, que esto puede estar abierto todo el día.
          return [...previos, entrante].slice(-200);
        });
      }),
    [],
  );

  useEffect(() => {
    fondo.current?.scrollTo({ top: fondo.current.scrollHeight, behavior: "smooth" });
  }, [pasos]);

  // Se agrupan por turno porque es la unidad que le importa a quien mira:
  // «esto es lo que hizo cuando le pedí aquello».
  const turnos = pasos.reduce<Map<string, PasoMotor[]>>((mapa, paso) => {
    const lista = mapa.get(paso.turno) ?? [];
    lista.push(paso);
    mapa.set(paso.turno, lista);
    return mapa;
  }, new Map());

  const rotulos: Record<EstadoCanal, string> = {
    conectando: "conectando",
    conectado: "escuchando",
    caido: "sin conexión",
  };

  return (
    <div className="proceso">
      <header className="proceso-cabecera">
        <span
          className={`proceso-pulso ${canal === "conectado" ? "vivo" : ""}`}
          aria-hidden
        />
        <h1>Qué está haciendo</h1>
        <span className="proceso-estado">{rotulos[canal]}</span>
      </header>

      <div className="proceso-lista" ref={fondo}>
        {pasos.length === 0 ? (
          <p className="proceso-vacio">
            Aquí aparecerá cada cosa que Vibi haga: los comandos que lanza, lo
            que busca y las herramientas que usa. Háblale y míralo.
          </p>
        ) : (
          [...turnos.entries()].map(([turno, delTurno]) => (
            <section key={turno} className="proceso-turno">
              {delTurno.map((paso, indice) => (
                <article
                  key={`${paso.tipo}-${paso.detalle}-${indice}`}
                  className="proceso-paso"
                  data-curso={
                    paso.estado.includes("RUNNING") || paso.estado.includes("PENDING")
                  }
                >
                  <span className="proceso-nombre">{nombreLegible(paso.tipo)}</span>
                  {paso.detalle && (
                    <code className="proceso-detalle">{resumirPaso(paso)}</code>
                  )}
                </article>
              ))}
            </section>
          ))
        )}
      </div>
    </div>
  );
}
