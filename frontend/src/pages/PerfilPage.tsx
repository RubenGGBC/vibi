import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Award,
  CheckCircle,
  Database,
  Eye,
  Globe,
  HardDrive,
  Info,
  Laptop,
  Layers,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  TrendingUp,
  UserCheck,
} from "lucide-react";
import { useState, type FormEvent } from "react";

import { EntrevistaModal } from "../components/EntrevistaModal";
import {
  borrarAfirmacion,
  borrarCapacidad,
  cambiarNivelCapacidad,
  crearAfirmacion,
  ejecutarRevision,
  fetchPerfil,
  perfilKeys,
  resetearPerfil,
} from "../lib/perfilApi";
import type {
  ClaseAfirmacion,
  NivelCapacidad,
  ProcedenciaAfirmacion,
  TipoCapacidad,
} from "../types";
import "../styles/perfil.css";

const CLASES: Array<{ id: "todas" | ClaseAfirmacion; label: string }> = [
  { id: "todas", label: "Todas" },
  { id: "dominio", label: "Dominio" },
  { id: "herramienta", label: "Herramientas" },
  { id: "preferencia", label: "Preferencias" },
  { id: "aficion", label: "Aficiones" },
];

const TIPOS: Array<{ id: "todas" | TipoCapacidad; label: string }> = [
  { id: "todas", label: "Todas" },
  { id: "mcp", label: "Servidores MCP" },
  { id: "skill", label: "Skills" },
  { id: "vigilancia", label: "Vigilancias" },
];

const PROCEDENCIAS: Record<ProcedenciaAfirmacion, { label: string; conf: number }> = {
  entrevista: { label: "Entrevista", conf: 0.6 },
  inventario: { label: "Inventario", conf: 0.4 },
  uso: { label: "Uso", conf: 0.8 },
};

export function PerfilPage() {
  const queryClient = useQueryClient();
  const [entrevistaAbierta, setEntrevistaAbierta] = useState(false);
  const [filtroClase, setFiltroClase] = useState<"todas" | ClaseAfirmacion>("todas");
  const [filtroTipo, setFiltroTipo] = useState<"todas" | TipoCapacidad>("todas");

  // Formulario nueva afirmación
  const [mostrandoFormAf, setMostrandoFormAf] = useState(false);
  const [nuevaClase, setNuevaClase] = useState<ClaseAfirmacion>("dominio");
  const [nuevoValor, setNuevoValor] = useState("");

  // Notificación de resultado del observador
  const [mensajeRevision, setMensajeRevision] = useState<string | null>(null);

  const query = useQuery({
    queryKey: perfilKeys.all,
    queryFn: fetchPerfil,
  });

  const mutationCrearAf = useMutation({
    mutationFn: (args: { clase: ClaseAfirmacion; valor: string }) =>
      crearAfirmacion(args.clase, args.valor, "entrevista"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: perfilKeys.all });
      setNuevoValor("");
      setMostrandoFormAf(false);
    },
  });

  const mutationBorrarAf = useMutation({
    mutationFn: borrarAfirmacion,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: perfilKeys.all });
    },
  });

  const mutationNivel = useMutation({
    mutationFn: (args: { id: number; nivel: NivelCapacidad }) =>
      cambiarNivelCapacidad(args.id, args.nivel),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: perfilKeys.all });
    },
  });

  const mutationBorrarCap = useMutation({
    mutationFn: borrarCapacidad,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: perfilKeys.all });
    },
  });

  const mutationRevision = useMutation({
    mutationFn: ejecutarRevision,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: perfilKeys.all });
      const apoyadas = data.apoyadas.length;
      const decaidas = data.decaidas.length;
      const retiradas = data.propuestas_retirada.length;
      setMensajeRevision(
        `Revisión completada: ${apoyadas} confirmadas por uso, ${decaidas} decaídas por inactividad, ${retiradas} propuestas de retirada.`
      );
      setTimeout(() => setMensajeRevision(null), 7000);
    },
  });

  const mutationResetear = useMutation({
    mutationFn: resetearPerfil,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: perfilKeys.all });
    },
  });

  const handleCrearAfirmacion = (e: FormEvent) => {
    e.preventDefault();
    if (!nuevoValor.trim()) return;
    mutationCrearAf.mutate({ clase: nuevaClase, valor: nuevoValor.trim() });
  };

  const handleResetear = () => {
    if (window.confirm("¿Seguro que quieres borrar todo el perfil y reiniciar las afirmaciones y capacidades aprendidas?")) {
      mutationResetear.mutate();
    }
  };

  const perfilData = query.data;
  const afirmaciones = (perfilData?.afirmaciones ?? []).filter(
    (a) => filtroClase === "todas" || a.clase === filtroClase
  );
  const capacidades = (perfilData?.capacidades ?? []).filter(
    (c) => filtroTipo === "todas" || c.tipo === filtroTipo
  );

  return (
    <section className="perfil-page" aria-label="Perfil de usuario">
      <header className="perfil-header">
        <div className="perfil-header-copy">
          <p className="eyebrow">Especialización de Vibi</p>
          <h1>Perfil de usuario</h1>
          <p>
            Vibi ajusta dinámicamente qué servidores MCP, herramientas y contexto ocupan turnos
            según tus afirmaciones y tu uso real verificado.
          </p>
        </div>

        <div className="perfil-actions">
          <button
            className="primary-button text-xs px-4 py-2 min-h-[2.6rem]"
            onClick={() => setEntrevistaAbierta(true)}
          >
            <Sparkles size={16} /> Entrevista de especialización
          </button>
          <button
            className="perfil-btn-secondary"
            disabled={mutationRevision.isPending}
            onClick={() => mutationRevision.mutate()}
            title="Lee contadores de uso y ajusta confianzas"
          >
            <RefreshCw size={14} className={mutationRevision.isPending ? "animate-spin" : ""} />
            {mutationRevision.isPending ? "Revisando…" : "Revisar uso ahora"}
          </button>
          <button
            className="perfil-btn-danger"
            disabled={mutationResetear.isPending}
            onClick={handleResetear}
            title="Borra todo el perfil y vuelve al catálogo base"
          >
            <Trash2 size={14} /> Borrar perfil
          </button>
        </div>
      </header>

      {mensajeRevision && (
        <div className="p-3 border border-emerald-500/30 rounded-xl bg-emerald-950/20 text-xs text-emerald-300 flex items-center gap-2">
          <CheckCircle size={16} />
          <span>{mensajeRevision}</span>
        </div>
      )}

      {/* KPI CARDS (MÉTRICAS TFG) */}
      <div className="perfil-kpis">
        <div className="perfil-kpi-card">
          <span className="perfil-kpi-label">
            <UserCheck size={14} className="text-violet-400" /> Afirmaciones
          </span>
          <span className="perfil-kpi-value">{perfilData?.metricas?.total_afirmaciones ?? 0}</span>
          <span className="perfil-kpi-desc">Hipótesis sobre tu profesión, herramientas y preferencias</span>
        </div>

        <div className="perfil-kpi-card">
          <span className="perfil-kpi-label">
            <Layers size={14} className="text-violet-400" /> Capacidades
          </span>
          <span className="perfil-kpi-value">{perfilData?.metricas?.total_capacidades ?? 0}</span>
          <span className="perfil-kpi-desc">Servidores MCP, skills y vigilancias configuradas</span>
        </div>

        <div className="perfil-kpi-card">
          <span className="perfil-kpi-label">
            <Award size={14} className="text-emerald-400" /> Tasa de Aceptación
          </span>
          <span className="perfil-kpi-value">
            {Math.round((perfilData?.metricas?.tasa_de_aceptacion ?? 0) * 100)}%
          </span>
          <span className="perfil-kpi-desc">Capacidades propuestas que mantienes en nivel completo</span>
        </div>

        <div className="perfil-kpi-card">
          <span className="perfil-kpi-label">
            <TrendingUp size={14} className="text-emerald-400" /> Supervivencia (14d)
          </span>
          <span className="perfil-kpi-value">
            {Math.round((perfilData?.metricas?.supervivencia_14dias ?? 0) * 100)}%
          </span>
          <span className="perfil-kpi-desc">Capacidades con uso activo a las 2 semanas de instalación</span>
        </div>
      </div>

      {/* RESUMEN MOTOR (GEMINI.md) */}
      <div className="perfil-resumen-card">
        <div className="perfil-resumen-header">
          <div className="flex items-center gap-2">
            <Eye size={16} className="text-violet-400" />
            <h2 className="text-sm font-bold text-stone-200">Quién tienes delante</h2>
          </div>
          <span className="perfil-resumen-tag">GEMINI.md</span>
        </div>
        {perfilData?.resumen ? (
          <p className="perfil-resumen-texto">{perfilData.resumen}</p>
        ) : (
          <p className="perfil-resumen-vacio">
            Sin afirmaciones con suficiente confianza (≥ 0,5). Realiza la entrevista o añade afirmaciones
            para que el motor conozca tu contexto en cada turno.
          </p>
        )}
      </div>

      {/* SECCIÓN AFIRMACIONES */}
      <div className="perfil-seccion">
        <div className="perfil-seccion-header">
          <div className="perfil-seccion-titulo">
            <Database size={18} className="text-violet-400" />
            <h2>Afirmaciones sobre ti</h2>
            <span className="text-xs text-stone-500 font-mono">({afirmaciones.length})</span>
          </div>

          <div className="flex items-center gap-2">
            <div className="perfil-filtro-tabs">
              {CLASES.map(({ id, label }) => (
                <button
                  key={id}
                  className={`perfil-filtro-tab ${filtroClase === id ? "activo" : ""}`}
                  onClick={() => setFiltroClase(id)}
                >
                  {label}
                </button>
              ))}
            </div>

            <button
              className="perfil-btn-secondary py-1 px-2.5 text-xs"
              onClick={() => setMostrandoFormAf(!mostrandoFormAf)}
            >
              <Plus size={14} /> Añadir
            </button>
          </div>
        </div>

        {mostrandoFormAf && (
          <form onSubmit={handleCrearAfirmacion} className="perfil-form-inline">
            <select
              value={nuevaClase}
              onChange={(e) => setNuevaClase(e.target.value as ClaseAfirmacion)}
            >
              <option value="dominio">Dominio</option>
              <option value="herramienta">Herramienta</option>
              <option value="preferencia">Preferencia</option>
              <option value="aficion">Afición</option>
            </select>
            <input
              type="text"
              value={nuevoValor}
              onChange={(e) => setNuevoValor(e.target.value)}
              placeholder="Valor o descripción (ej. medicina, python, apuntes en pdf...)"
              autoFocus
            />
            <button
              type="submit"
              className="primary-button text-xs px-4 min-h-[2.3rem]"
              disabled={mutationCrearAf.isPending}
            >
              Guardar
            </button>
            <button
              type="button"
              className="perfil-btn-secondary py-1 px-3 text-xs"
              onClick={() => setMostrandoFormAf(false)}
            >
              Cancelar
            </button>
          </form>
        )}

        {afirmaciones.length === 0 ? (
          <div className="p-8 border border-stone-800 rounded-xl text-center text-xs text-stone-500">
            No hay afirmaciones registradas en esta categoría. Pulsa «Entrevista de especialización»
            o «Añadir» para registrar tu área o herramientas.
          </div>
        ) : (
          <div className="perfil-grid-afirmaciones">
            {afirmaciones.map((af) => {
              const pct = Math.round(af.confianza * 100);
              const procedenciaInfo = PROCEDENCIAS[af.procedencia] || { label: af.procedencia, conf: 0.5 };
              return (
                <div key={af.id} className="afirmacion-card">
                  <div className="afirmacion-top">
                    <div>
                      <span className={`badge-clase badge-clase-${af.clase}`}>{af.clase}</span>
                      <div className="afirmacion-valor mt-1">{af.valor}</div>
                      <span className="badge-procedencia">Origen: {procedenciaInfo.label}</span>
                    </div>

                    <button
                      className="icon-button w-7 h-7 text-stone-500 hover:text-rose-400"
                      onClick={() => mutationBorrarAf.mutate(af.id)}
                      title="Eliminar afirmación"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>

                  <div className="afirmacion-confianza-bar">
                    <div className="confianza-meter" title={`Confianza: ${pct}%`}>
                      <div className="confianza-meter-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="confianza-pct">{pct}%</span>
                  </div>

                  <div className="afirmacion-stats">
                    <span>
                      Apoyos: <strong className="text-emerald-400">+{af.apoyos}</strong>
                    </span>
                    <span>
                      Contras: <strong className="text-rose-400">-{af.contras}</strong>
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* SECCIÓN CAPACIDADES */}
      <div className="perfil-seccion">
        <div className="perfil-seccion-header">
          <div className="perfil-seccion-titulo">
            <Layers size={18} className="text-violet-400" />
            <h2>Capacidades instaladas</h2>
            <span className="text-xs text-stone-500 font-mono">({capacidades.length})</span>
          </div>

          <div className="perfil-filtro-tabs">
            {TIPOS.map(({ id, label }) => (
              <button
                key={id}
                className={`perfil-filtro-tab ${filtroTipo === id ? "activo" : ""}`}
                onClick={() => setFiltroTipo(id)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {capacidades.length === 0 ? (
          <div className="p-8 border border-stone-800 rounded-xl text-center text-xs text-stone-500">
            No hay capacidades aprobadas en esta categoría. Puedes descubrir servidores con la «Entrevista de especialización».
          </div>
        ) : (
          <div className="perfil-grid-capacidades">
            {capacidades.map((cap) => (
              <div key={cap.id} className="capacidad-card">
                <div className="capacidad-icono uppercase">
                  {cap.tipo === "mcp" ? "MCP" : cap.tipo === "skill" ? "SKL" : "VIG"}
                </div>

                <div className="capacidad-detalles">
                  <div className="capacidad-titular">
                    <span className="capacidad-referencia">{cap.referencia}</span>
                    <span className={`badge-nivel badge-nivel-${cap.nivel}`}>
                      {cap.nivel === "completo"
                        ? "Completo"
                        : cap.nivel === "catalogo"
                        ? "En catálogo"
                        : "Propuesta de retirada"}
                    </span>
                    {cap.transporte && (
                      <span className="badge-transporte" title={cap.transporte === "remoto" ? "No corre código local, datos viajan a servidor remoto" : "Corre código de un paquete de terceros local"}>
                        {cap.transporte === "remoto" ? <Globe size={11} /> : <Laptop size={11} />}
                        {cap.transporte === "remoto" ? "Remoto" : "Local"}
                      </span>
                    )}
                  </div>

                  <p className="capacidad-justificacion">{cap.justificacion}</p>

                  <div className="capacidad-meta">
                    <span>Usos registrados: <strong>{cap.usos}</strong></span>
                    {cap.ultimo_uso && (
                      <span>Último uso: {new Date(cap.ultimo_uso * 1000).toLocaleDateString()}</span>
                    )}
                  </div>
                </div>

                <div className="capacidad-acciones">
                  <select
                    className="capacidad-select-nivel"
                    value={cap.nivel}
                    onChange={(e) =>
                      mutationNivel.mutate({ id: cap.id, nivel: e.target.value as NivelCapacidad })
                    }
                    title="Cambiar nivel de presencia"
                  >
                    <option value="completo">Completo (Activo)</option>
                    <option value="catalogo">En catálogo (Inactivo)</option>
                    <option value="propuesta_retirada">Propuesta retirada</option>
                  </select>

                  <button
                    className="icon-button w-8 h-8 text-stone-500 hover:text-rose-400"
                    onClick={() => mutationBorrarCap.mutate(cap.id)}
                    title="Eliminar capacidad"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {entrevistaAbierta && <EntrevistaModal onClose={() => setEntrevistaAbierta(false)} />}
    </section>
  );
}
