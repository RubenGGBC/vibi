import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GraduationCap, MessageSquare, PanelRightClose } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChatPanel } from "../components/ChatPanel";
import {
  Deslizadores,
  Lecturas,
  Leyenda,
  Reproductores,
  Simulaciones,
  tieneReproductor,
} from "../components/estudio/Controles";
import { Escenario } from "../components/estudio/Escenario";
import { BarraManipulacion, motivoDeBloqueo } from "../components/estudio/Manipulacion";
import { Tutor } from "../components/estudio/Tutor";
import type { Transformacion } from "../components/estudio/contexto";
import { suscribirEventos } from "../lib/eventBus";
import {
  ajustarObjeto,
  aplicarAjusteLocal,
  aplicarObjeto,
  aplicarPaso,
  escenaKey,
  irAPaso,
  pedirEscena,
  subirCaptura,
} from "../lib/estudio/api";
import {
  clave,
  redondear,
  VISTA_INICIAL,
  type Herramienta,
  type Seleccion,
  type Vista3D,
} from "../lib/estudio/manipulacion";
import type { Escena, Objeto } from "../lib/estudio/tipos";
import {
  guardarPreferenciaVoz,
  leerPreferenciaVoz,
  narracionDePaso,
  useVozTutor,
} from "../lib/estudio/vozTutor";
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
  // Cerrado: la clase la da Vibi en su panel. El chat es para ver la conversación entera.
  const [chatAbierto, setChatAbierto] = useState(false);
  const [seleccion, setSeleccion] = useState<Seleccion | null>(null);
  const [herramienta, setHerramienta] = useState<Herramienta>("elegir");
  const [vista, setVista] = useState<Vista3D>(VISTA_INICIAL);
  const [errorAjuste, setErrorAjuste] = useState<string | null>(null);
  const [articulaciones, setArticulaciones] = useState<Record<string, number>>({});
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

  const [vozActiva, setVozActiva] = useState(leerPreferenciaVoz);
  // Delante de todo lo que el alumno le dice a Vibi desde aquí, por voz o escrito.
  const prefijoTutor = () =>
    escena?.pasos.length ? `(Estudio, paso ${escena.paso_actual + 1})` : "(Estudio)";
  const voz = useVozTutor(vozActiva, prefijoTutor);
  const cambiarVoz = useCallback((activa: boolean) => {
    guardarPreferenciaVoz(activa);
    setVozActiva(activa);
  }, []);

  // Mientras Vibi prepara la respuesta, lo que hay en el lienzo es de antes:
  // se vela hasta que la escena cambie, para no leerlo como la respuesta.
  const versionAlPreguntar = useRef<number | null>(null);
  const pensando = voz.estado === "thinking";
  if (pensando && versionAlPreguntar.current === null && escena) {
    versionAlPreguntar.current = escena.version;
  } else if (!pensando) {
    versionAlPreguntar.current = null;
  }
  const preparando = pensando && escena !== undefined && versionAlPreguntar.current === escena.version;

  // Al llegar a un paso, Vibi lo cuenta. Al abrir la página no: aún no ha
  // habido un gesto del alumno y el navegador no dejaría sonar nada.
  const pasoNarrado = useRef<number | null>(null);
  useEffect(() => {
    if (!escena?.pasos.length) {
      // Escena nueva: su primer paso llega mientras se monta, no se narra.
      pasoNarrado.current = null;
      return;
    }
    const indice = escena.paso_actual;
    if (pasoNarrado.current !== null && pasoNarrado.current !== indice && escena.pasos[indice]) {
      voz.narrar(narracionDePaso(escena.pasos[indice]));
    }
    pasoNarrado.current = indice;
  }, [escena?.paso_actual, escena?.pasos.length]);

  const paso = useMemo(
    () => (escena ? estadoDePaso(escena, escena.paso_actual) : null),
    [escena],
  );

  const objetos = useMemo(
    () => (escena && paso ? escena.elementos.filter((e): e is Objeto => e.tipo === "objeto" && paso.visibles.has(e.id)) : []),
    [escena, paso],
  );
  const hayPartes = objetos.some((o) => Object.keys(o.partes ?? {}).length > 1);
  const bloqueo = motivoDeBloqueo(seleccion, objetos);

  // Lo elegido puede desaparecer (otro paso, o el modelo lo quita).
  useEffect(() => {
    if (seleccion && !objetos.some((o) => o.id === seleccion.id)) setSeleccion(null);
  }, [objetos, seleccion]);
  useEffect(() => setErrorAjuste(null), [seleccion]);

  const elegir = useCallback((nueva: Seleccion | null) => setSeleccion(nueva), []);

  const guardarAjuste = useCallback(
    (elegida: Seleccion, t: Transformacion) => {
      const ajuste = {
        parte: elegida.parte,
        posicion: t.posicion.map((v) => redondear(v, 4)),
        rotacion: t.rotacion.map((v) => redondear(v, 2)),
        escala: t.escala.map((v) => redondear(v, 4)),
      };
      aplicarAjusteLocal(client, elegida.id, ajuste);
      setErrorAjuste(null);
      ajustarObjeto(elegida.id, ajuste)
        .then((objeto) => aplicarObjeto(client, objeto))
        .catch((e: unknown) => {
          setErrorAjuste(e instanceof Error ? e.message : "No se pudo guardar");
          void client.invalidateQueries({ queryKey: escenaKey });
        });
    },
    [client],
  );

  const restablecer = useCallback(
    (elegida: Seleccion) => {
      ajustarObjeto(elegida.id, { parte: elegida.parte, restablecer: true })
        .then((objeto) => aplicarObjeto(client, objeto))
        .catch((e: unknown) => setErrorAjuste(e instanceof Error ? e.message : "No se pudo restablecer"));
    },
    [client],
  );

  // Atajos de los editores 3D: W mover, E girar, R escalar, H ocultar, Esc soltar.
  useEffect(() => {
    const alPulsar = (evento: KeyboardEvent) => {
      const destino = evento.target as HTMLElement | null;
      if (destino && (destino.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(destino.tagName))) return;
      if (evento.metaKey || evento.ctrlKey || evento.altKey) return;
      const tecla = evento.key.toLowerCase();
      if (tecla === "escape") {
        setSeleccion(null);
        setHerramienta("elegir");
      } else if (seleccion && (tecla === "w" || tecla === "e" || tecla === "r")) {
        setHerramienta(tecla === "w" ? "mover" : tecla === "e" ? "girar" : "escalar");
      } else if (seleccion && tecla === "h") {
        setVista((v) => ({ ...v, ocultos: new Set([...v.ocultos, clave(seleccion)]) }));
        setSeleccion(null);
      }
    };
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [seleccion]);

  // Lo mismo para la barra de arriba y para la tarjeta de lo elegido.
  const mandos = {
    objetos,
    seleccion,
    herramienta,
    vista,
    bloqueo,
    error: errorAjuste,
    hayPartes,
    articulaciones,
    valores,
    onArticulacion: (k: string, valor: number | null) =>
      setArticulaciones((actuales) => {
        const siguientes = { ...actuales };
        if (valor === null) delete siguientes[k];
        else siguientes[k] = valor;
        return siguientes;
      }),
    onHerramienta: setHerramienta,
    onSeleccion: elegir,
    onVista: setVista,
    onRestablecer: restablecer,
  };

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
            <span>{chatAbierto ? "Ocultar conversación" : "Ver conversación"}</span>
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
                seleccion={seleccion}
                herramienta={herramienta}
                vista={vista}
                bloqueado={bloqueo !== null}
                articulaciones={articulaciones}
                onSeleccionar={elegir}
                onSoltar={guardarAjuste}
              />
              {objetos.length > 0 && <BarraManipulacion lugar="barra" {...mandos} />}
              <div className="estudio-lateral">
                <Leyenda escena={escena} visibles={paso.visibles} />
                {objetos.length > 0 && <BarraManipulacion lugar="tarjeta" {...mandos} />}
              </div>
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
          {preparando && hayElementos && (
            <div className="estudio-preparando" role="status">
              <p>{(voz.etiqueta || "Vibi está preparando la explicación").replace(/[.…]+$/, "")}…</p>
            </div>
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
                  <li key={ejemplo}>
                    <button type="button" onClick={() => voz.preguntar(ejemplo)} disabled={pensando}>
                      «{ejemplo}»
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <Tutor escena={escena} voz={voz} vozActiva={vozActiva} onVozActiva={cambiarVoz} onIr={irA} />
      </div>

      {chatAbierto && (
        <aside className="estudio-chat" aria-label="Chat con Vibi">
          <button type="button" className="estudio-chat-cerrar" onClick={() => setChatAbierto(false)}>
            <PanelRightClose size={15} /> Volver a la escena
          </button>
          <ChatPanel contexto={prefijoTutor} />
        </aside>
      )}
    </section>
  );
}
