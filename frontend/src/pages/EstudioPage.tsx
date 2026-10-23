import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GraduationCap, MessageSquare, PanelRightClose } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChatPanel } from "../components/ChatPanel";
import {
  Deslizadores,
  Lecturas,
  Leyenda,
  Pasos,
  Reproductores,
  Simulaciones,
  tieneReproductor,
} from "../components/estudio/Controles";
import { Escenario } from "../components/estudio/Escenario";
import { suscribirEventos } from "../lib/eventBus";
import { aplicarPaso, escenaKey, irAPaso, pedirEscena, subirCaptura } from "../lib/estudio/api";
import type { Escena } from "../lib/estudio/tipos";
import { estadoDePaso, valoresIniciales } from "../lib/estudio/visibilidad";

const EJEMPLOS = [
  "Explícame por qué la serie armónica diverge",
  "Quiero jugar con un péndulo y ver cómo cambia el periodo",
  "Enséñame cómo funciona Dijkstra con un ejemplo",
  "Compara burbuja y quicksort",
  "Enséñame la molécula de cafeína",
  "¿Qué pinta tiene z = sin(x)·cos(y)?",
];

const VELOCIDAD_REPRODUCTOR_MS = 520;

/** Una huella de lo que reproduce cada elemento: si cambia, se rebobina. */
function firmaReproductor(escena: Escena): Record<string, string> {
  const firmas: Record<string, string> = {};
  for (const e of escena.elementos) {
    if (e.tipo === "grafo" && e.recorrido) {
      firmas[e.id] = `${e.recorrido.algoritmo}|${e.recorrido.origen}|${e.recorrido.destino}|${e.recorrido.fotogramas.length}`;
    } else if (e.tipo === "ordenacion") {
      firmas[e.id] = `${e.algoritmo}|${e.valores.join(",")}`;
    }
  }
  return firmas;
}

export function EstudioPage() {
  const client = useQueryClient();
  const { data: escena, isLoading, error } = useQuery({
    queryKey: escenaKey,
    queryFn: pedirEscena,
    staleTime: Infinity,
  });

  const [valores, setValores] = useState<Record<string, number>>({});
  const [fotogramas, setFotogramas] = useState<Record<string, number>>({});
  const [reproduciendo, setReproduciendo] = useState<Record<string, boolean>>({});
  const [enMarcha, setEnMarcha] = useState(true);
  const [reinicio, setReinicio] = useState(0);
  const [chatAbierto, setChatAbierto] = useState(
    () => typeof window === "undefined" || window.innerWidth > 1100,
  );
  const lienzo = useRef<HTMLCanvasElement | null>(null);
  const firmas = useRef<Record<string, string>>({});

  // Los deslizadores conservan lo que movió el alumno mientras sigan existiendo.
  const parametrosClave = JSON.stringify(escena?.parametros ?? []);
  useEffect(() => {
    if (!escena) return;
    setValores((previos) => valoresIniciales(escena, previos));
  }, [parametrosClave]);

  // Un algoritmo nuevo (o ejecutado de nuevo) arranca desde el principio, solo.
  useEffect(() => {
    if (!escena) return;
    const nuevas = firmaReproductor(escena);
    const cambiados = Object.keys(nuevas).filter((id) => firmas.current[id] !== nuevas[id]);
    firmas.current = nuevas;
    if (!cambiados.length) return;
    setFotogramas((f) => ({ ...f, ...Object.fromEntries(cambiados.map((id) => [id, 0])) }));
    setReproduciendo((r) => ({ ...r, ...Object.fromEntries(cambiados.map((id) => [id, true])) }));
  }, [escena]);

  const conReproductor = useMemo(
    () => (escena ? escena.elementos.filter(tieneReproductor) : []),
    [escena],
  );

  useEffect(() => {
    const activos = conReproductor.filter((e) => reproduciendo[e.id]);
    if (!activos.length) return;
    const reloj = window.setInterval(() => {
      setFotogramas((actuales) => {
        const siguientes = { ...actuales };
        for (const e of activos) {
          const total = e.tipo === "grafo" ? e.recorrido?.fotogramas.length ?? 0 : e.fotogramas.length;
          const siguiente = (actuales[e.id] ?? 0) + 1;
          if (siguiente >= total) {
            setReproduciendo((r) => ({ ...r, [e.id]: false }));
          } else {
            siguientes[e.id] = siguiente;
          }
        }
        return siguientes;
      });
    }, VELOCIDAD_REPRODUCTOR_MS);
    return () => window.clearInterval(reloj);
  }, [conReproductor, reproduciendo]);

  // El modelo pide mirar la escena: la primera ventana que pueda, contesta.
  useEffect(
    () =>
      suscribirEventos((evento) => {
        if (evento.tipo !== "estudio_captura" || !lienzo.current) return;
        lienzo.current.toBlob(
          (imagen) => {
            if (imagen) void subirCaptura(evento.captura_id, imagen).catch(() => undefined);
          },
          "image/jpeg",
          0.85,
        );
      }),
    [],
  );

  const irA = useCallback(
    (indice: number) => {
      aplicarPaso(client, indice);
      void irAPaso(indice).catch(() => undefined);
    },
    [client],
  );

  const paso = useMemo(
    () => (escena ? estadoDePaso(escena, escena.paso_actual) : null),
    [escena],
  );

  const hayElementos = Boolean(escena?.elementos.length);
  const haySimulaciones = Boolean(
    escena?.elementos.some((e) => e.tipo === "simulacion" || e.tipo === "sistema"),
  );
  const hayMovimiento =
    haySimulaciones ||
    Boolean(
      escena?.elementos.some(
        (e) => e.tipo === "molecula" || (e.tipo === "objeto" && e.anima),
      ),
    );

  return (
    <section className={`estudio-page${chatAbierto ? " con-chat" : ""}`} aria-label="Estudio">
      <div className="estudio-main">
        <header className="estudio-cabecera">
          <div>
            <span className="estudio-seccion">
              <GraduationCap size={14} /> Estudio
            </span>
            <h1>{escena?.titulo || "Aprende viéndolo"}</h1>
          </div>
          <button
            type="button"
            className="estudio-chat-toggle"
            onClick={() => setChatAbierto((v) => !v)}
            aria-label={chatAbierto ? "Ocultar chat" : "Abrir chat"}
          >
            {chatAbierto ? <PanelRightClose size={16} /> : <MessageSquare size={16} />}
            <span>{chatAbierto ? "Ocultar chat" : "Hablar con Vibi"}</span>
          </button>
        </header>

        <div className="estudio-escenario">
          {isLoading && <p className="estudio-vacio">Cargando la escena…</p>}
          {error && <p className="estudio-vacio">No se pudo cargar la escena.</p>}
          {escena && paso && hayElementos && (
            <>
              <Escenario
                escena={escena}
                paso={paso}
                valores={valores}
                fotogramas={fotogramas}
                enMarcha={enMarcha}
                reinicio={reinicio}
                onLienzo={(c) => {
                  lienzo.current = c;
                }}
              />
              <Leyenda escena={escena} visibles={paso.visibles} />
              {haySimulaciones && <Lecturas />}
              <div className="estudio-hud-abajo">
                <Deslizadores
                  escena={escena}
                  valores={valores}
                  onCambio={(id, v) => setValores((actual) => ({ ...actual, [id]: v }))}
                />
                {hayMovimiento && (
                  <Simulaciones
                    enMarcha={enMarcha}
                    onAlternar={() => setEnMarcha((v) => !v)}
                    onReiniciar={() => setReinicio((v) => v + 1)}
                  />
                )}
                <Reproductores
                  elementos={conReproductor.filter((e) => paso.visibles.has(e.id))}
                  fotogramas={fotogramas}
                  enReproduccion={reproduciendo}
                  onFotograma={(id, i) => {
                    setReproduciendo((r) => ({ ...r, [id]: false }));
                    setFotogramas((f) => ({ ...f, [id]: i }));
                  }}
                  onAlternar={(id) => {
                    const e = conReproductor.find((x) => x.id === id);
                    const total = e?.tipo === "grafo" ? e.recorrido?.fotogramas.length ?? 0 : e?.fotogramas.length ?? 0;
                    if (!reproduciendo[id] && (fotogramas[id] ?? 0) >= total - 1) {
                      setFotogramas((f) => ({ ...f, [id]: 0 }));
                    }
                    setReproduciendo((r) => ({ ...r, [id]: !r[id] }));
                  }}
                />
              </div>
            </>
          )}
          {escena && !hayElementos && (
            <div className="estudio-vacio">
              <GraduationCap size={34} />
              <h2>Pídele a Vibi que te lo enseñe</h2>
              <p>
                Vibi monta aquí la explicación: gráficas, simulaciones, algoritmos o
                moléculas que puedes tocar, con todo calculado por el engine.
              </p>
              <ul>
                {EJEMPLOS.map((ejemplo) => (
                  <li key={ejemplo}>«{ejemplo}»</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {escena && <Pasos escena={escena} indice={escena.paso_actual} onIr={irA} />}
      </div>

      {chatAbierto && (
        <aside className="estudio-chat" aria-label="Chat con Vibi">
          <button type="button" className="estudio-chat-cerrar" onClick={() => setChatAbierto(false)}>
            <PanelRightClose size={15} /> Volver a la escena
          </button>
          <ChatPanel />
        </aside>
      )}
    </section>
  );
}
