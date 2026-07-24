import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Play, Plus, ShieldCheck, Wrench } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError, apiFetch } from "../lib/api";
import type { Tool } from "../types";

interface ToolsResponse {
  herramientas: Tool[];
}

interface ExecutionResponse {
  invocation_id: string;
  status: "succeeded";
  result: Record<string, unknown>;
}

export function ToolsPage() {
  const client = useQueryClient();
  const [showBuilder, setShowBuilder] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [primitive, setPrimitive] = useState("files.search");
  const [preset, setPreset] = useState("");
  const [scope, setScope] = useState<"personal" | "lab">("personal");
  const [result, setResult] = useState("");
  const query = useQuery({
    queryKey: ["tools"],
    queryFn: () => apiFetch<ToolsResponse>("/api/herramientas"),
  });
  const create = useMutation({
    mutationFn: () =>
      apiFetch<Tool>("/api/herramientas", {
        method: "POST",
        body: JSON.stringify({
          name,
          description,
          primitive_id: primitive,
          scope,
          bound_arguments:
            primitive === "files.search"
              ? { query: preset, limit: 20 }
              : {},
        }),
      }),
    onSuccess: async () => {
      setName("");
      setDescription("");
      setPreset("");
      setShowBuilder(false);
      await client.invalidateQueries({ queryKey: ["tools"] });
    },
  });
  const execute = useMutation({
    mutationFn: (tool: Tool) =>
      apiFetch<ExecutionResponse>(`/api/herramientas/${tool.id}/ejecutar`, {
        method: "POST",
        body: JSON.stringify({ arguments: {} }),
      }),
    onSuccess: ({ result: nextResult }) => {
      const files = nextResult.files;
      setResult(
        Array.isArray(files)
          ? `La herramienta encontró ${files.length} archivo(s).`
          : JSON.stringify(nextResult, null, 2),
      );
    },
  });
  const toggle = useMutation({
    mutationFn: (tool: Tool) =>
      apiFetch<Tool>(`/api/herramientas/${tool.id}/estado`, {
        method: "POST",
        body: JSON.stringify({ enabled: !tool.enabled }),
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["tools"] });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };
  const mutationError = create.error ?? execute.error ?? toggle.error;
  const error = mutationError
    ? mutationError instanceof ApiError
      ? mutationError.message
      : "No se pudo completar la operación."
    : null;

  return (
    <section className="page tools-page">
      <header className="page-header resource-header">
        <div>
          <p className="eyebrow">Capacidades extensibles</p>
          <h1>Herramientas</h1>
          <p>
            Morgana compone capacidades auditables. Las herramientas personales
            son tuyas; las del laboratorio requieren permisos de administrador.
          </p>
        </div>
        <button className="primary-button tool-builder-trigger" onClick={() => setShowBuilder((current) => !current)}>
          <Plus size={18} /> Crear tool
        </button>
      </header>

      {showBuilder && (
        <form className="tool-builder" onSubmit={submit}>
          <div>
            <p className="eyebrow">Nueva composición</p>
            <h2>Construye sobre una capacidad segura</h2>
            <p>La herramienta no carga código arbitrario: configura una primitiva revisada por Morgana.</p>
          </div>
          <label>Nombre<input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>Descripción<textarea required maxLength={1000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <div className="tool-builder-row">
            <label>Capacidad base<select value={primitive} onChange={(event) => setPrimitive(event.target.value)}><option value="files.search">Buscar archivos</option><option value="system.health">Comprobar Morgana</option></select></label>
            <label>Alcance<select value={scope} onChange={(event) => setScope(event.target.value as "personal" | "lab")}><option value="personal">Solo para mí</option><option value="lab">Laboratorio</option></select></label>
          </div>
          {primitive === "files.search" && <label>Búsqueda preconfigurada<input value={preset} onChange={(event) => setPreset(event.target.value)} placeholder="Ej. matrículas" /></label>}
          <button className="primary-button" disabled={create.isPending}>{create.isPending ? "Creando…" : "Crear herramienta"}</button>
        </form>
      )}

      {result && <p className="success-message" role="status">{result}</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}

      {query.isPending ? (
        <div className="resource-grid"><i className="resource-skeleton" /><i className="resource-skeleton" /></div>
      ) : query.isError ? (
        <p className="inline-error">No se pudo cargar el catálogo.</p>
      ) : (
        <ul className="resource-grid tool-grid" aria-label="Catálogo de herramientas">
          {query.data?.herramientas.map((tool) => (
            <li key={tool.id} className={`resource-card tool-card${tool.enabled ? "" : " tool-disabled"}`}>
              <div className="tool-card-topline">
                <span className="resource-icon">{tool.primitive_id === "system.health" ? <Activity size={21} /> : <Wrench size={21} />}</span>
                <span className={`scope-badge scope-${tool.scope}`}>{tool.scope}</span>
              </div>
              <h2>{tool.name}</h2>
              <p>{tool.description}</p>
              <div className="permission-list"><ShieldCheck size={14} /> {tool.permissions.length ? tool.permissions.join(" · ") : "Sin permisos especiales"}</div>
              <div className="tool-actions">
                <button className="reject-button" disabled={!tool.enabled || execute.isPending} onClick={() => execute.mutate(tool)}><Play size={15} /> Ejecutar</button>
                {tool.scope === "personal" && <button className="text-button" disabled={toggle.isPending} onClick={() => toggle.mutate(tool)}>{tool.enabled ? "Desactivar" : "Activar"}</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
