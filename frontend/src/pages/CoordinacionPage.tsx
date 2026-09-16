import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Eye, EyeOff, Plus, Radio, ShieldCheck, UsersRound } from "lucide-react";

import { apiFetch } from "../lib/api";
import {
  anadirMiembro,
  crearEquipo,
  crearTareaEquipo,
  declararEstadoTarea,
  decidirSeguimiento,
  equipoPanelKey,
  equiposKey,
  fetchEquipoPanel,
  fetchEquipos,
  fetchSeguimientosPendientes,
  proponerSeguimiento,
  seguimientosPendientesKey,
} from "../lib/equipos";
import { fetchNodos, nodosKey } from "../lib/nodos";
import type { EquipoPanel, NodeDevice, TareaEquipo, User } from "../types";

const ESTADOS: Record<string, string> = {
  abierta: "abierta",
  en_progreso: "en progreso",
  esperando_revision: "espera revisión",
  entregada: "entregada",
  cerrada: "cerrada",
};

const SENALES: Record<string, string> = {
  avance: "hubo avance",
  sin_avance: "sin avance",
  entregado: "artefacto entregado",
  fallo_repetido: "fallo repetido",
  tarea_larga: "tarea larga",
  revision_pendiente: "revisión pendiente",
  integracion_rota: "integración rota",
};

function haceCuando(segundos: number): string {
  const diferencia = Math.max(0, Math.round(Date.now() / 1000 - segundos));
  if (diferencia < 60) return "ahora";
  if (diferencia < 3600) return `hace ${Math.round(diferencia / 60)} min`;
  return `hace ${Math.round(diferencia / 3600)} h`;
}

function PropuestaRuta({
  panel,
  tarea,
  nodos,
  propio,
  onDone,
}: {
  panel: EquipoPanel;
  tarea: TareaEquipo;
  nodos: NodeDevice[];
  propio: boolean;
  onDone: () => void;
}) {
  const [ruta, setRuta] = useState("");
  const [senal, setSenal] = useState<"avance" | "sin_avance" | "entregado">("avance");
  const [nodo, setNodo] = useState(nodos[0]?.id ?? "");
  useEffect(() => {
    if (!nodo && nodos[0]) setNodo(nodos[0].id);
  }, [nodo, nodos]);
  const mutation = useMutation({
    mutationFn: () =>
      proponerSeguimiento(panel.equipo.id, {
        tarea_id: tarea.id,
        node_id: propio ? nodo : undefined,
        senal,
        parametros: senal === "sin_avance" ? { ruta, horas: 8 } : { ruta },
        justificacion:
          senal === "entregado"
            ? "Avisar únicamente cuando aparezca el artefacto esperado."
            : senal === "sin_avance"
              ? "Detectar ocho horas observadas sin cambios, sin leer contenido."
              : "Detectar cambios de metadatos dentro de la ruta, sin publicar nombres ni contenido.",
      }),
    onSuccess: () => {
      setRuta("");
      onDone();
    },
  });

  return (
    <details className="coord-propuesta">
      <summary><Eye size={14} /> Proponer observación local</summary>
      <div className="coord-propuesta-cuerpo">
        <label>
          Señal que podrá publicar
          <select value={senal} onChange={(e) => setSenal(e.target.value as typeof senal)}>
            <option value="avance">Hubo avance</option>
            <option value="sin_avance">Ocho horas sin avance</option>
            <option value="entregado">Apareció el entregable</option>
          </select>
        </label>
        <label>
          Ruta observada — se queda en tu seguimiento privado
          <input value={ruta} onChange={(e) => setRuta(e.target.value)} placeholder="/proyectos/informe" />
        </label>
        {propio ? (
          <label>
            Dispositivo
            <select value={nodo} onChange={(e) => setNodo(e.target.value)}>
              {nodos.map((item) => <option key={item.id} value={item.id}>{item.nombre}</option>)}
            </select>
          </label>
        ) : (
          <p><ShieldCheck size={14} /> El dispositivo lo resuelve Vibi y su dueño lo verá antes de aprobar.</p>
        )}
        <p><ShieldCheck size={14} /> El equipo solo recibirá “{SENALES[senal]}”. Nunca la ruta ni el contenido.</p>
        <button
          type="button"
          className="coord-button"
          disabled={!ruta.trim() || (propio && !nodo) || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          Pedir aprobación
        </button>
        {mutation.isError && <span className="inline-error">No se pudo crear la propuesta.</span>}
      </div>
    </details>
  );
}

export function CoordinacionPage() {
  const queryClient = useQueryClient();
  const [seleccionado, setSeleccionado] = useState("");
  const [nuevoEquipo, setNuevoEquipo] = useState("");
  const [nuevoMiembro, setNuevoMiembro] = useState("");
  const [nuevaTarea, setNuevaTarea] = useState("");
  const [asignada, setAsignada] = useState("");

  const yo = useQuery({ queryKey: ["me"], queryFn: () => apiFetch<User>("/api/yo") });
  const equipos = useQuery({ queryKey: equiposKey, queryFn: fetchEquipos });
  const nodos = useQuery<NodeDevice[]>({ queryKey: nodosKey, queryFn: fetchNodos });
  const pendientes = useQuery({
    queryKey: seguimientosPendientesKey,
    queryFn: fetchSeguimientosPendientes,
    refetchInterval: 5_000,
  });

  useEffect(() => {
    if (!seleccionado && equipos.data?.[0]) setSeleccionado(equipos.data[0].id);
    if (seleccionado && equipos.data && !equipos.data.some((e) => e.id === seleccionado)) {
      setSeleccionado(equipos.data[0]?.id ?? "");
    }
  }, [equipos.data, seleccionado]);

  const panel = useQuery({
    queryKey: equipoPanelKey(seleccionado),
    queryFn: () => fetchEquipoPanel(seleccionado),
    enabled: Boolean(seleccionado),
    refetchInterval: 5_000,
  });

  const refrescar = () => {
    void queryClient.invalidateQueries({ queryKey: equiposKey });
    if (seleccionado) void queryClient.invalidateQueries({ queryKey: equipoPanelKey(seleccionado) });
    void queryClient.invalidateQueries({ queryKey: seguimientosPendientesKey });
  };

  const crear = useMutation({
    mutationFn: () => crearEquipo(nuevoEquipo),
    onSuccess: (creado) => {
      setNuevoEquipo("");
      setSeleccionado(creado.id);
      refrescar();
    },
  });
  const sumar = useMutation({
    mutationFn: () => anadirMiembro(seleccionado, nuevoMiembro),
    onSuccess: () => { setNuevoMiembro(""); refrescar(); },
  });
  const tarea = useMutation({
    mutationFn: () => crearTareaEquipo(seleccionado, nuevaTarea, asignada),
    onSuccess: () => { setNuevaTarea(""); refrescar(); },
  });
  const decidir = useMutation({
    mutationFn: ({ id, accion }: { id: string; accion: "aprobar" | "rechazar" | "revocar" }) =>
      decidirSeguimiento(id, accion),
    onSuccess: refrescar,
  });
  const declarar = useMutation({
    mutationFn: ({ tareaId, estado }: { tareaId: number; estado: TareaEquipo["estado"] }) =>
      declararEstadoTarea(seleccionado, tareaId, estado),
    onSuccess: refrescar,
  });

  useEffect(() => {
    if (!asignada && panel.data?.equipo.miembros[0]) {
      setAsignada(panel.data.equipo.miembros[0].user_id);
    }
  }, [panel.data, asignada]);

  const creencias = useMemo(() => {
    const mapa = new Map<number, EquipoPanel["creencias"]>();
    for (const creencia of panel.data?.creencias ?? []) {
      if (creencia.tarea_id == null) continue;
      mapa.set(creencia.tarea_id, [...(mapa.get(creencia.tarea_id) ?? []), creencia]);
    }
    return mapa;
  }, [panel.data]);

  return (
    <section className="coord-page" aria-label="Coordinación de equipo">
      <header className="coord-hero">
        <div>
          <p className="eyebrow">Estado observado · no declarado</p>
          <h1>Coordinación</h1>
          <p>El nodo publica cambios del trabajo. El contenido se queda con su dueño.</p>
        </div>
        <div className="coord-live"><Radio size={15} /><span>{panel.data?.senales.length ?? 0}</span> señales visibles</div>
      </header>

      {(pendientes.data?.length ?? 0) > 0 && (
        <section className="coord-consentimiento" aria-label="Seguimientos por aprobar">
          <header><ShieldCheck size={18} /><div><b>Tu nodo espera permiso</b><span>Nada empieza a observarse hasta que decidas.</span></div></header>
          {pendientes.data?.map((item) => (
            <article key={item.id}>
              <div>
                <strong>{item.tarea_titulo}</strong>
                <p>{item.justificacion}</p>
                <code>{item.node_nombre} · publicará {SENALES[item.senal] ?? item.senal}</code>
              </div>
              <div className="coord-actions">
                <button onClick={() => decidir.mutate({ id: item.id, accion: "rechazar" })}>Rechazar</button>
                <button className="coord-button" onClick={() => decidir.mutate({ id: item.id, accion: "aprobar" })}>Aprobar</button>
              </div>
            </article>
          ))}
        </section>
      )}

      <div className="coord-layout">
        <aside className="coord-equipos">
          <p className="coord-label">Equipos humanos</p>
          <nav>
            {(equipos.data ?? []).map((item) => (
              <button key={item.id} data-active={item.id === seleccionado} onClick={() => setSeleccionado(item.id)}>
                <UsersRound size={15} /><span>{item.nombre}<small>{item.miembros.length} personas</small></span>
              </button>
            ))}
          </nav>
          <form onSubmit={(e) => { e.preventDefault(); if (nuevoEquipo.trim()) crear.mutate(); }}>
            <input value={nuevoEquipo} onChange={(e) => setNuevoEquipo(e.target.value)} placeholder="Nombre del equipo" aria-label="Nombre del equipo" />
            <button type="submit" aria-label="Crear equipo"><Plus size={15} /></button>
          </form>
        </aside>

        {!seleccionado ? (
          <div className="coord-empty"><UsersRound size={30} /><h2>Crea el primer equipo</h2><p>Empieza con personas y tareas; la observación siempre se aprueba después.</p></div>
        ) : panel.isPending ? (
          <div className="loading-list" aria-label="Cargando equipo"><i /><i /></div>
        ) : panel.isError || !panel.data ? (
          <p className="inline-error">No se pudo leer el equipo.</p>
        ) : (
          <main className="coord-tablero">
            <section className="coord-identidad">
              <div><p className="coord-label">Equipo activo</p><h2>{panel.data.equipo.nombre}</h2></div>
              <ul>{panel.data.equipo.miembros.map((m) => (
                <li key={m.user_id}>
                  <i
                    aria-hidden="true"
                    title={`Colores de la Vibi de ${m.nombre}`}
                    style={{
                      background: `conic-gradient(${m.color_sombrero} 0 42%, ${m.color_antifaz} 42% 72%, ${m.color_cara} 72% 100%)`,
                    }}
                  />
                  <span>{m.nombre}<small>{m.rol}</small></span>
                </li>
              ))}</ul>
              {panel.data.equipo.mi_rol === "coordinador" && (
                <form onSubmit={(e) => { e.preventDefault(); if (nuevoMiembro.trim()) sumar.mutate(); }}>
                  <input value={nuevoMiembro} onChange={(e) => setNuevoMiembro(e.target.value)} placeholder="Usuario de Vibi" aria-label="Añadir miembro" />
                  <button type="submit">Añadir</button>
                </form>
              )}
            </section>

            <section className="coord-trabajo">
              <header><div><p className="coord-label">Mapa de trabajo</p><h3>Tareas sostenidas por evidencia</h3></div><Activity size={20} /></header>
              <form className="coord-nueva-tarea" onSubmit={(e) => { e.preventDefault(); if (nuevaTarea.trim() && asignada) tarea.mutate(); }}>
                <input value={nuevaTarea} onChange={(e) => setNuevaTarea(e.target.value)} placeholder="Nueva tarea del equipo" aria-label="Título de tarea" />
                <select value={asignada} onChange={(e) => setAsignada(e.target.value)} aria-label="Persona asignada">
                  {panel.data.equipo.miembros.map((m) => <option key={m.user_id} value={m.user_id}>{m.nombre}</option>)}
                </select>
                <button className="coord-button" type="submit">Abrir tarea</button>
              </form>
              <div className="coord-tareas">
                {panel.data.tareas.map((item) => {
                  const observadas = creencias.get(item.id) ?? [];
                  const esMia = item.asignada_a === yo.data?.id;
                  return (
                    <article key={item.id} data-state={item.estado}>
                      <header><span>{ESTADOS[item.estado]}</span><time>{haceCuando(item.actualizada_en)}</time></header>
                      <h4>{item.titulo}</h4>
                      <p className="coord-responsable">{item.asignada_nombre ?? "Sin asignar"}</p>
                      {esMia && (
                        <label className="coord-declaracion">
                          Tu estado declarado
                          <select
                            value={item.estado}
                            onChange={(e) => declarar.mutate({
                              tareaId: item.id,
                              estado: e.target.value as TareaEquipo["estado"],
                            })}
                          >
                            {Object.entries(ESTADOS).map(([valor, etiqueta]) => (
                              <option key={valor} value={valor}>{etiqueta}</option>
                            ))}
                          </select>
                        </label>
                      )}
                      {observadas.map((c) => (
                        <div className="coord-creencia" key={c.id}>
                          <i style={{ "--confianza": `${Math.round(c.confianza * 100)}%` } as CSSProperties} />
                          <span>{c.clase}: {c.valor}<small>{Math.round(c.confianza * 100)}% · {c.procedencia}</small></span>
                        </div>
                      ))}
                      {(esMia || panel.data.equipo.mi_rol === "coordinador") && (
                        <PropuestaRuta
                          panel={panel.data}
                          tarea={item}
                          nodos={nodos.data ?? []}
                          propio={esMia}
                          onDone={refrescar}
                        />
                      )}
                    </article>
                  );
                })}
                {!panel.data.tareas.length && <p className="coord-vacio">Aún no hay tareas. El coordinador no sustituye un gestor de proyectos: solo necesita saber qué trabajo sostener.</p>}
              </div>
            </section>

            <aside className="coord-traza">
              <header><div><p className="coord-label">Trazabilidad</p><h3>Lo que llegó</h3></div><EyeOff size={18} /></header>
              <p className="coord-privacidad">Sin rutas, títulos de ventana ni contenido.</p>
              <ol>
                {panel.data.senales.map((senal) => (
                  <li key={senal.id}><i /><div><b>{SENALES[senal.nombre] ?? senal.nombre}</b><span>Tarea #{senal.tarea_id} · {haceCuando(senal.observada_en)}</span></div></li>
                ))}
              </ol>
              {!panel.data.senales.length && <p className="coord-vacio">Silencio. Ningún seguimiento aprobado ha observado un cambio.</p>}
              {panel.data.seguimientos.filter((s) => s.user_id === yo.data?.id).map((s) => (
                <div className="coord-seguimiento" key={s.id}>
                  <span><b>{SENALES[s.senal] ?? s.senal}</b><small>{s.estado}</small></span>
                  {s.estado === "aprobado" && <button onClick={() => decidir.mutate({ id: s.id, accion: "revocar" })}>Revocar</button>}
                </div>
              ))}
            </aside>
          </main>
        )}
      </div>
    </section>
  );
}
