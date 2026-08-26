import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, ChevronRight, Compass, HardDrive, HelpCircle, Loader2, Plus, Sparkles, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import {
  completarEntrevista,
  fetchHipotesis,
  generarPropuestas,
  perfilKeys,
} from "../lib/perfilApi";
import type { ClaseAfirmacion, Hipotesis, Propuesta } from "../types";
import "../styles/perfil.css";

interface EntrevistaModalProps {
  onClose: () => void;
}

type Paso = "evidencia" | "preguntas" | "propuestas" | "confirmacion";

export function EntrevistaModal({ onClose }: EntrevistaModalProps) {
  const queryClient = useQueryClient();
  const [paso, setPaso] = useState<Paso>("evidencia");

  // Paso 1: Hipótesis del equipo
  const hipotesisQuery = useQuery({
    queryKey: perfilKeys.hipotesis,
    queryFn: fetchHipotesis,
  });
  const [hipotesisConfirmadas, setHipotesisConfirmadas] = useState<Record<string, boolean>>({});

  // Inicializar confirmaciones cuando cargan las hipótesis
  useEffect(() => {
    if (hipotesisQuery.data?.hipotesis) {
      const initial: Record<string, boolean> = {};
      hipotesisQuery.data.hipotesis.forEach((h, idx) => {
        initial[`${h.clase}-${h.valor}-${idx}`] = true;
      });
      setHipotesisConfirmadas(initial);
    }
  }, [hipotesisQuery.data]);

  // Paso 2: Preguntas
  const [paraQue, setParaQue] = useState("");
  const [queEsperas, setQueEsperas] = useState("");
  const [queAyuda, setQueAyuda] = useState("");
  const [campoLibre, setCampoLibre] = useState("");

  // Paso 3: Propuestas
  const [propuestas, setPropuestas] = useState<Propuesta[]>([]);
  const [seleccionadas, setSeleccionadas] = useState<Record<string, boolean>>({});
  const [buscandoPropuestas, setBuscandoPropuestas] = useState(false);
  const [terminoExtra, setTerminoExtra] = useState("");
  const [errorBusquedaManual, setErrorBusquedaManual] = useState("");

  // Paso 4: Finalizar
  const mutationCompletar = useMutation({
    mutationFn: completarEntrevista,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: perfilKeys.all });
      onClose();
    },
  });

  const irABusqueda = async () => {
    setPaso("propuestas");
    setBuscandoPropuestas(true);

    // Los términos de las respuestas libres los deriva el servidor (mismas
    // pistas por palabra completa que usa el mapa de carpetas, no un
    // `.includes()` suelto aquí): así una respuesta fuera de un puñado de
    // categorías fijas no cae siempre en el mismo respaldo genérico.
    const pedidos = new Set<string>();
    const adyacentes = new Set<string>();

    hipotesisQuery.data?.hipotesis.forEach((h, idx) => {
      if (hipotesisConfirmadas[`${h.clase}-${h.valor}-${idx}`]) {
        pedidos.add(h.valor);
        if (h.clase === "dominio") adyacentes.add("notes");
      }
    });

    const textoLibre = [paraQue, queEsperas, queAyuda, campoLibre].join(" ");

    try {
      const lista = await generarPropuestas(Array.from(pedidos), Array.from(adyacentes), textoLibre);
      setPropuestas(lista);
      const seleccion: Record<string, boolean> = {};
      lista.forEach((p) => {
        seleccion[p.referencia] = true;
      });
      setSeleccionadas(seleccion);
    } catch {
      setPropuestas([]);
    } finally {
      setBuscandoPropuestas(false);
    }
  };

  const agregarTerminoManual = async (event: FormEvent) => {
    event.preventDefault();
    if (!terminoExtra.trim()) return;
    setBuscandoPropuestas(true);
    setErrorBusquedaManual("");
    try {
      const extra = await generarPropuestas([terminoExtra.trim()], []);
      const nuevas = [...propuestas];
      const nuevasSel = { ...seleccionadas };
      extra.forEach((p) => {
        if (!nuevas.some((item) => item.referencia === p.referencia)) {
          nuevas.push(p);
          nuevasSel[p.referencia] = true;
        }
      });
      setPropuestas(nuevas);
      setSeleccionadas(nuevasSel);
      if (extra.length === 0) {
        setErrorBusquedaManual(`Sin resultados verificados para «${terminoExtra.trim()}».`);
      } else {
        setTerminoExtra("");
      }
    } catch {
      setErrorBusquedaManual("No se pudo consultar el registro. Inténtalo de nuevo.");
    } finally {
      setBuscandoPropuestas(false);
    }
  };

  const handleFinalizar = () => {
    // Afirmaciones resultantes
    const afirmaciones: Array<{ clase: ClaseAfirmacion; valor: string; procedencia?: string }> = [];

    // Hipótesis confirmadas
    hipotesisQuery.data?.hipotesis.forEach((h, idx) => {
      if (hipotesisConfirmadas[`${h.clase}-${h.valor}-${idx}`]) {
        afirmaciones.push({
          clase: h.clase as ClaseAfirmacion,
          valor: h.valor,
          procedencia: "inventario",
        });
      }
    });

    // Declaraciones de preguntas
    if (paraQue.trim()) {
      afirmaciones.push({ clase: "preferencia", valor: paraQue.trim().slice(0, 100), procedencia: "entrevista" });
    }
    if (campoLibre.trim()) {
      afirmaciones.push({ clase: "aficion", valor: campoLibre.trim().slice(0, 100), procedencia: "entrevista" });
    }

    // Capacidades aprobadas
    const capacidadesAprobadas = propuestas
      .filter((p) => seleccionadas[p.referencia])
      .map((p) => ({
        tipo: p.tipo,
        referencia: p.referencia,
        justificacion: p.justificacion,
        transporte: p.transporte,
      }));

    mutationCompletar.mutate({
      afirmaciones,
      capacidades: capacidadesAprobadas,
    });
  };

  const pedidosList = propuestas.filter((p) => p.bloque === "pedido");
  const encajanList = propuestas.filter((p) => p.bloque === "encaja");

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="entrevista-dialog" role="dialog" aria-modal="true">
        <button className="icon-button dialog-close" onClick={onClose} aria-label="Cerrar">
          <X size={18} />
        </button>

        <header className="entrevista-pasos-nav">
          {(() => {
            const pasoIndex = { evidencia: 1, preguntas: 2, propuestas: 3, confirmacion: 4 }[paso];
            return (
              <>
                <div className={`entrevista-paso-dot ${paso === "evidencia" ? "activo" : pasoIndex > 1 ? "completado" : ""}`}>
                  <span>1. Entorno</span>
                </div>
                <ChevronRight size={14} className="text-stone-600" />
                <div className={`entrevista-paso-dot ${paso === "preguntas" ? "activo" : pasoIndex > 2 ? "completado" : ""}`}>
                  <span>2. Preguntas</span>
                </div>
                <ChevronRight size={14} className="text-stone-600" />
                <div className={`entrevista-paso-dot ${paso === "propuestas" ? "activo" : pasoIndex > 3 ? "completado" : ""}`}>
                  <span>3. Propuesta</span>
                </div>
                <ChevronRight size={14} className="text-stone-600" />
                <div className={`entrevista-paso-dot ${paso === "confirmacion" ? "activo" : ""}`}>
                  <span>4. Confirmar</span>
                </div>
              </>
            );
          })()}
        </header>

        <div className="entrevista-cuerpo">
          {/* PASO 1: EVIDENCIA DEL EQUIPO */}
          {paso === "evidencia" && (
            <div className="entrevista-bloque">
              <div className="entrevista-bloque-titulo">
                <HardDrive size={18} className="text-violet-400" />
                <span>Escaneo silencioso del entorno</span>
              </div>
              <p className="text-xs text-stone-400 leading-relaxed">
                Vibi revisa el mapa de carpetas y extensiones de tu equipo local para
                formular hipótesis iniciales. <strong>Ningún archivo ni contenido sale de tu ordenador.</strong>
              </p>

              {hipotesisQuery.isLoading ? (
                <div className="flex items-center gap-3 p-4 border border-violet-900/30 rounded-xl bg-violet-950/20">
                  <Loader2 className="animate-spin text-violet-400" size={18} />
                  <span className="text-xs text-stone-300">Consultando mapa del equipo...</span>
                </div>
              ) : hipotesisQuery.data?.hipotesis && hipotesisQuery.data.hipotesis.length > 0 ? (
                <div className="grid gap-2 mt-2">
                  <span className="text-xs font-semibold text-stone-300">
                    Hipótesis encontradas — confirma las que encajen contigo:
                  </span>
                  {hipotesisQuery.data.hipotesis.map((h, idx) => {
                    const key = `${h.clase}-${h.valor}-${idx}`;
                    const checked = !!hipotesisConfirmadas[key];
                    return (
                      <label
                        key={key}
                        className={`flex items-start gap-3 p-3 border rounded-xl cursor-pointer transition-colors ${
                          checked
                            ? "border-violet-500/40 bg-violet-950/20"
                            : "border-stone-800 bg-stone-950/30 opacity-70"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) =>
                            setHipotesisConfirmadas({
                              ...hipotesisConfirmadas,
                              [key]: e.target.checked,
                            })
                          }
                          className="mt-0.5"
                        />
                        <div className="text-xs">
                          <span className="font-bold text-stone-200 uppercase tracking-wide">
                            {h.valor}
                          </span>{" "}
                          <span className="text-violet-300/80">({h.clase})</span>
                          <p className="text-stone-400 text-[11px] mt-0.5">Apoyado en: {h.evidencia}</p>
                        </div>
                      </label>
                    );
                  })}
                </div>
              ) : (
                <div className="p-4 border border-stone-800 rounded-xl bg-stone-950/40 text-xs text-stone-400">
                  {hipotesisQuery.data?.tiene_nodo
                    ? "El equipo conectado no presenta carpetas con patrones específicos conocidos. No hay problema: pasamos a las preguntas directas."
                    : "No hay ningún dispositivo conectado en este momento. Continuamos directamente con las preguntas."}
                </div>
              )}
            </div>
          )}

          {/* PASO 2: PREGUNTAS DE LA ENTREVISTA */}
          {paso === "preguntas" && (
            <div className="entrevista-bloque">
              <div className="entrevista-bloque-titulo">
                <HelpCircle size={18} className="text-violet-400" />
                <span>Cuatro preguntas para afinar a Vibi</span>
              </div>
              <p className="text-xs text-stone-400">
                Responde brevemente con tus propias palabras. Con esto Vibi buscará las capacidades adecuadas en el registro oficial.
              </p>

              <div className="entrevista-pregunta">
                <label>1. ¿Para qué vas a usar Vibi?</label>
                <textarea
                  value={paraQue}
                  onChange={(e) => setParaQue(e.target.value)}
                  placeholder="ej. Estudiar medicina, programar en Python, gestionar apuntes y proyectos..."
                  rows={2}
                />
              </div>

              <div className="entrevista-pregunta">
                <label>2. ¿Qué esperas de ella?</label>
                <textarea
                  value={queEsperas}
                  onChange={(e) => setQueEsperas(e.target.value)}
                  placeholder="ej. Que sea concisa, que lea mis PDF con precisión, que me ahorre tiempo buscando..."
                  rows={2}
                />
              </div>

              <div className="entrevista-pregunta">
                <label>3. ¿En qué te gustaría que te ayudara y hoy haces a mano?</label>
                <textarea
                  value={queAyuda}
                  onChange={(e) => setQueAyuda(e.target.value)}
                  placeholder="ej. Extraer resúmenes de bibliografía, formatear notas, sincronizar carpetas..."
                  rows={2}
                />
              </div>

              <div className="entrevista-pregunta">
                <label>4. Campo libre (lo que quieras contarle, aficiones incluidas):</label>
                <textarea
                  value={campoLibre}
                  onChange={(e) => setCampoLibre(e.target.value)}
                  placeholder="ej. Me gusta el ciclismo, toco la guitarra, prefiero respuestas en español..."
                  rows={2}
                />
              </div>
            </div>
          )}

          {/* PASO 3: PROPUESTAS EN DOS BLOQUES */}
          {paso === "propuestas" && (
            <div className="entrevista-bloque">
              <div className="entrevista-bloque-titulo">
                <Sparkles size={18} className="text-violet-400" />
                <span>Propuesta de capacidades verificadas</span>
              </div>
              <p className="text-xs text-stone-400">
                Solo se proponen servidores activos del registro oficial con transporte verificado.
                Elige cuáles deseas aprobar para tu entorno:
              </p>

              {buscandoPropuestas ? (
                <div className="flex items-center justify-center gap-3 p-8 border border-stone-800 rounded-xl bg-stone-950/30">
                  <Loader2 className="animate-spin text-violet-400" size={24} />
                  <span className="text-xs text-stone-300">Buscando y verificando servidores en el registro oficial...</span>
                </div>
              ) : (
                <>
                  {/* Bloque 1: Lo que has pedido */}
                  <div className="propuestas-bloque">
                    <span className="text-xs font-bold text-violet-300 uppercase tracking-wider">
                      1. Lo que has pedido
                    </span>
                    <p className="text-[11px] text-stone-400">Derivado directamente de tus respuestas e intereses.</p>
                    {pedidosList.length === 0 ? (
                      <span className="text-xs text-stone-500 italic">No se encontraron MCPs directos para este bloque.</span>
                    ) : (
                      pedidosList.map((p) => (
                        <label key={p.referencia} className="propuesta-item cursor-pointer">
                          <input
                            type="checkbox"
                            checked={!!seleccionadas[p.referencia]}
                            onChange={(e) =>
                              setSeleccionadas({ ...seleccionadas, [p.referencia]: e.target.checked })
                            }
                            className="propuesta-check"
                          />
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="propuesta-titulo">{p.titulo}</span>
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] font-mono uppercase ${
                                  p.transporte === "remoto"
                                    ? "propuesta-badge-remoto"
                                    : "propuesta-badge-local"
                                }`}
                              >
                                {p.transporte === "remoto" ? "🌐 Remoto" : "💻 Local"}
                              </span>
                            </div>
                            <p className="propuesta-desc">{p.justificacion}</p>
                          </div>
                        </label>
                      ))
                    )}
                  </div>

                  {/* Bloque 2: Lo que además encaja */}
                  <div className="propuestas-bloque mt-2">
                    <span className="text-xs font-bold text-violet-300 uppercase tracking-wider">
                      2. Lo que además encaja
                    </span>
                    <p className="text-[11px] text-stone-400">
                      Ampliación por adyacencia de tu perfil y herramientas relacionadas.
                    </p>
                    {encajanList.length === 0 ? (
                      <span className="text-xs text-stone-500 italic">Sin sugerencias adicionales por adyacencia.</span>
                    ) : (
                      encajanList.map((p) => (
                        <label key={p.referencia} className="propuesta-item cursor-pointer">
                          <input
                            type="checkbox"
                            checked={!!seleccionadas[p.referencia]}
                            onChange={(e) =>
                              setSeleccionadas({ ...seleccionadas, [p.referencia]: e.target.checked })
                            }
                            className="propuesta-check"
                          />
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="propuesta-titulo">{p.titulo}</span>
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] font-mono uppercase ${
                                  p.transporte === "remoto"
                                    ? "propuesta-badge-remoto"
                                    : "propuesta-badge-local"
                                }`}
                              >
                                {p.transporte === "remoto" ? "🌐 Remoto" : "💻 Local"}
                              </span>
                            </div>
                            <p className="propuesta-desc">{p.justificacion}</p>
                          </div>
                        </label>
                      ))
                    )}
                  </div>

                  {/* Búsqueda manual adicional */}
                  <form onSubmit={agregarTerminoManual} className="flex gap-2 mt-2">
                    <input
                      type="text"
                      value={terminoExtra}
                      onChange={(e) => setTerminoExtra(e.target.value)}
                      placeholder="Buscar otro servidor MCP (ej. github, weather, sqlite)..."
                      className="flex-1 min-h-[2.4rem] px-3 py-1 bg-stone-950 border border-stone-800 rounded-lg text-xs text-stone-200"
                    />
                    <button type="submit" className="perfil-btn-secondary py-1 px-3 text-xs">
                      <Plus size={14} /> Buscar
                    </button>
                  </form>
                  {errorBusquedaManual && (
                    <p className="text-[11px] text-amber-400/90 mt-1">{errorBusquedaManual}</p>
                  )}
                </>
              )}
            </div>
          )}

          {/* PASO 4: CONFIRMACIÓN */}
          {paso === "confirmacion" && (
            <div className="entrevista-bloque">
              <div className="entrevista-bloque-titulo">
                <CheckCircle2 size={18} className="text-emerald-400" />
                <span>Confirmar especialización</span>
              </div>
              <p className="text-xs text-stone-400">
                Todo listo para aplicar tu perfil. Vibi actualizará su archivo de contexto de motor (<code>GEMINI.md</code>)
                y conectará los servidores MCP seleccionados.
              </p>

              <div className="p-4 border border-stone-800 rounded-xl bg-stone-950/40 text-xs grid gap-2">
                <span className="font-semibold text-stone-300">Capacidades que quedarán activas en nivel completo:</span>
                <ul className="list-disc list-inside text-stone-400 space-y-1">
                  {propuestas
                    .filter((p) => seleccionadas[p.referencia])
                    .map((p) => (
                      <li key={p.referencia}>
                        <strong className="text-stone-200">{p.titulo}</strong> ({p.referencia}) — {p.transporte}
                      </li>
                    ))}
                  {propuestas.filter((p) => seleccionadas[p.referencia]).length === 0 && (
                    <li className="italic text-stone-500">Ningún servidor MCP adicional seleccionado.</li>
                  )}
                </ul>
              </div>
            </div>
          )}
        </div>

        <footer className="entrevista-footer">
          {paso === "evidencia" && (
            <>
              <button className="perfil-btn-secondary" onClick={onClose}>
                Cancelar
              </button>
              <button className="primary-button px-5 text-xs min-h-[2.5rem]" onClick={() => setPaso("preguntas")}>
                Siguiente: Preguntas
              </button>
            </>
          )}

          {paso === "preguntas" && (
            <>
              <button className="perfil-btn-secondary" onClick={() => setPaso("evidencia")}>
                Atrás
              </button>
              <button className="primary-button px-5 text-xs min-h-[2.5rem]" onClick={irABusqueda}>
                Siguiente: Ver propuestas
              </button>
            </>
          )}

          {paso === "propuestas" && (
            <>
              <button className="perfil-btn-secondary" onClick={() => setPaso("preguntas")}>
                Atrás
              </button>
              <button className="primary-button px-5 text-xs min-h-[2.5rem]" onClick={() => setPaso("confirmacion")}>
                Siguiente: Confirmar
              </button>
            </>
          )}

          {paso === "confirmacion" && (
            <>
              <button className="perfil-btn-secondary" onClick={() => setPaso("propuestas")}>
                Atrás
              </button>
              <button
                className="primary-button px-6 text-xs min-h-[2.5rem]"
                disabled={mutationCompletar.isPending}
                onClick={handleFinalizar}
              >
                {mutationCompletar.isPending ? "Aplicando perfil…" : "Finalizar y Aplicar"}
              </button>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}
