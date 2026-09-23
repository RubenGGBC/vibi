import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BookOpenText,
  ClipboardList,
  Code2,
  Copy,
  FilePlus2,
  FolderKanban,
  Gauge,
  History,
  Pencil,
  Play,
  Plus,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  ToggleLeft,
  ToggleRight,
  Wrench,
  X,
} from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { ApiError, apiFetch } from "../lib/api";
import type {
  Tool,
  ToolInvocation,
  ToolSchemaProperty,
  ToolUsage,
} from "../types";

interface ToolsResponse {
  herramientas: Tool[];
}

interface ExecutionResponse {
  invocation_id: string;
  status: "succeeded";
  result: Record<string, unknown>;
}

interface InvocationsResponse {
  invocations: ToolInvocation[];
}

interface ToolPayload {
  name: string;
  description: string;
  primitive_id: string;
  scope: "personal" | "lab";
  bound_arguments: Record<string, unknown>;
}

type PanelMode = "editor" | "runner" | "history" | null;
type ScopeFilter = "all" | Tool["scope"];

const EMPTY_USAGE: ToolUsage = {
  total: 0,
  succeeded: 0,
  failed: 0,
  denied: 0,
  success_rate: null,
  last_used_at: null,
  average_duration_ms: null,
};

const FIELD_LABELS: Record<string, string> = {
  query: "Consulta",
  limit: "Límite",
  file_id: "Archivo",
  state: "Estado",
  project: "Proyecto",
  category: "Categoría",
  name: "Nombre del archivo",
  content: "Contenido",
};

const SCOPE_LABELS: Record<Tool["scope"], string> = {
  system: "Base",
  personal: "Personal",
  lab: "Lab",
};

const STATUS_LABELS: Record<ToolInvocation["status"], string> = {
  running: "En curso",
  succeeded: "Correcta",
  failed: "Fallida",
  denied: "Rechazada",
};

const ERROR_CODE_LABELS: Record<string, string> = {
  invalid_arguments: "Argumentos inválidos",
  execution_failed: "Fallo durante la ejecución",
};

function resolvedSchema(schema: ToolSchemaProperty): ToolSchemaProperty {
  const variants = schema.anyOf ?? schema.oneOf;
  const concrete = variants?.find((variant) => variant.type !== "null");
  return concrete ? { ...schema, ...concrete, anyOf: undefined, oneOf: undefined } : schema;
}

function schemaType(schema: ToolSchemaProperty) {
  return Array.isArray(schema.type)
    ? schema.type.find((candidate) => candidate !== "null")
    : schema.type;
}

function normalizedValue(schema: ToolSchemaProperty, value: unknown) {
  const type = schemaType(schema);
  if ((type === "object" || type === "array") && typeof value === "string") {
    try {
      return JSON.parse(value) as unknown;
    } catch {
      return value;
    }
  }
  return value;
}

function normalizedArguments(tool: Tool, values: Record<string, unknown>) {
  const properties = tool.input_schema.properties ?? {};
  return Object.fromEntries(
    Object.entries(values)
      .filter(([, value]) => value !== undefined)
      .map(([name, value]) => [
        name,
        normalizedValue(resolvedSchema(properties[name] ?? {}), value),
      ]),
  );
}

function fieldLabel(name: string, schema: ToolSchemaProperty) {
  return FIELD_LABELS[name] ?? schema.title ?? name.replaceAll("_", " ");
}

function toolIcon(tool: Tool) {
  if (tool.kind === "script") return <Code2 size={19} />;
  if (tool.primitive_id === "system.health") return <Activity size={19} />;
  if (tool.primitive_id === "files.create_note") return <FilePlus2 size={19} />;
  if (tool.primitive_id.startsWith("files.")) return <BookOpenText size={19} />;
  if (tool.primitive_id.startsWith("tasks.")) return <ClipboardList size={19} />;
  if (tool.primitive_id.startsWith("projects.")) return <FolderKanban size={19} />;
  if (tool.primitive_id.startsWith("activity.")) return <Gauge size={19} />;
  return <Wrench size={19} />;
}

function schemaEntries(tool: Tool): Array<[string, ToolSchemaProperty]> {
  return Object.entries(tool.input_schema.properties ?? {}).map(([name, schema]) => [
    name,
    resolvedSchema(schema),
  ]);
}

function SchemaInput({
  name,
  schema,
  value,
  onChange,
  required = false,
  suffix = "",
}: {
  name: string;
  schema: ToolSchemaProperty;
  value: unknown;
  onChange: (value: unknown) => void;
  required?: boolean;
  suffix?: string;
}) {
  const label = `${fieldLabel(name, schema)}${suffix ? ` ${suffix}` : ""}`;
  const type = schemaType(schema);

  if (schema.enum) {
    return (
      <label className="tool-field">
        <span>{label}</span>
        <select
          aria-label={label}
          required={required}
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(event) => {
            if (event.target.value === "") {
              onChange(undefined);
              return;
            }
            const selected = schema.enum?.find(
              (option) => String(option) === event.target.value,
            );
            onChange(selected);
          }}
        >
          {!required && <option value="">Cualquiera</option>}
          {schema.enum
            .filter((option) => option !== null)
            .map((option) => (
              <option key={String(option)} value={String(option)}>
                {String(option)}
              </option>
            ))}
        </select>
      </label>
    );
  }

  if (type === "boolean") {
    return (
      <label className="tool-field">
        <span>{label}</span>
        <select
          aria-label={label}
          required={required}
          value={value === undefined || value === null ? "" : value ? "true" : "false"}
          onChange={(event) =>
            onChange(
              event.target.value === "" ? undefined : event.target.value === "true",
            )
          }
        >
          <option value="">Sin fijar</option>
          <option value="false">No</option>
          <option value="true">Sí</option>
        </select>
      </label>
    );
  }

  if (type === "integer" || type === "number") {
    return (
      <label className="tool-field">
        <span>{label}</span>
        <input
          aria-label={label}
          required={required}
          type="number"
          min={schema.minimum}
          max={schema.maximum}
          step={type === "integer" ? 1 : "any"}
          value={typeof value === "number" ? value : ""}
          onChange={(event) =>
            onChange(event.target.value === "" ? undefined : Number(event.target.value))
          }
        />
      </label>
    );
  }

  if (type === "object" || type === "array") {
    const serialized =
      typeof value === "string"
        ? value
        : value === undefined
          ? ""
          : JSON.stringify(value, null, 2);
    return (
      <label className="tool-field">
        <span>{label}</span>
        <textarea
          aria-label={label}
          required={required}
          spellCheck={false}
          value={serialized}
          onChange={(event) => onChange(event.target.value)}
          placeholder={type === "array" ? "[]" : "{}"}
        />
        <small>Introduce JSON válido.</small>
      </label>
    );
  }

  if (name === "content" || (schema.maxLength ?? 0) > 1_000) {
    return (
      <label className="tool-field">
        <span>{label}</span>
        <textarea
          aria-label={label}
          required={required}
          minLength={schema.minLength}
          maxLength={schema.maxLength}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    );
  }

  return (
    <label className="tool-field">
      <span>{label}</span>
      <input
        aria-label={label}
        required={required}
        minLength={schema.minLength}
        maxLength={schema.maxLength}
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onChange(event.target.value)}
      />
      {schema.description && <small>{schema.description}</small>}
    </label>
  );
}

function ToolEditor({
  tool,
  primitives,
  onClose,
  onSave,
  pending,
}: {
  tool: Tool | null;
  primitives: Tool[];
  onClose: () => void;
  onSave: (toolId: string | null, payload: ToolPayload) => void;
  pending: boolean;
}) {
  const initialPrimitive = tool?.primitive_id ?? primitives[0]?.id ?? "";
  const [name, setName] = useState(tool?.name ?? "");
  const [description, setDescription] = useState(tool?.description ?? "");
  const [primitiveId, setPrimitiveId] = useState(initialPrimitive);
  const [scope, setScope] = useState<"personal" | "lab">(
    tool?.scope === "lab" ? "lab" : "personal",
  );
  const [bound, setBound] = useState<Record<string, unknown>>(
    tool?.bound_arguments ?? {},
  );
  const [presetFields, setPresetFields] = useState<string[]>(
    Object.keys(tool?.bound_arguments ?? {}),
  );
  const primitive = primitives.find((candidate) => candidate.id === primitiveId);
  const primitiveRemoved = tool !== null && primitive === undefined;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const selectedBound = Object.fromEntries(
      presetFields
        .filter((field) => bound[field] !== undefined)
        .map((field) => [field, bound[field]]),
    );
    onSave(tool?.id ?? null, {
      name,
      description,
      primitive_id: primitive?.id ?? primitiveId,
      scope,
      bound_arguments: primitive
        ? normalizedArguments(primitive, selectedBound)
        : selectedBound,
    });
  };

  return (
    <form className="tool-panel tool-editor-panel" onSubmit={submit}>
      <div className="tool-panel-heading">
        <div>
          <p className="eyebrow">{tool ? "Reconfigurar módulo" : "Nuevo módulo"}</p>
          <h2>{tool ? "Editar herramienta" : "Componer herramienta"}</h2>
        </div>
        <button type="button" className="tool-icon-button" onClick={onClose} aria-label="Cerrar editor">
          <X size={17} />
        </button>
      </div>

      <label className="tool-field">
        <span>Nombre</span>
        <input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="tool-field">
        <span>Descripción</span>
        <textarea required maxLength={1_000} value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
      <div className="tool-field-pair">
        <label className="tool-field">
          <span>Capacidad base</span>
          <select
            value={primitiveId}
            onChange={(event) => {
              setPrimitiveId(event.target.value);
              setBound({});
              setPresetFields([]);
            }}
          >
            {primitiveRemoved && (
              <option value={primitiveId} disabled>
                {primitiveId} · retirada
              </option>
            )}
            {primitives.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.name}
              </option>
            ))}
          </select>
        </label>
        <label className="tool-field">
          <span>Alcance</span>
          <select value={scope} onChange={(event) => setScope(event.target.value as "personal" | "lab")}>
            <option value="personal">Solo para mí</option>
            <option value="lab">Laboratorio</option>
          </select>
        </label>
      </div>

      <fieldset className="tool-preset-fieldset">
        <legend>Valores preconfigurados</legend>
        <p>Activa solo los datos que quieras fijar. El resto se pedirá al ejecutar.</p>
        {primitive && schemaEntries(primitive).length ? (
          schemaEntries(primitive).map(([field, schema]) => {
            const label = fieldLabel(field, schema);
            const selected = presetFields.includes(field);
            return (
              <div className={`tool-preset-row${selected ? " is-selected" : ""}`} key={field}>
                <label className="tool-preset-toggle">
                  <input
                    type="checkbox"
                    checked={selected}
                    aria-label={`Preconfigurar ${label}`}
                    onChange={(event) => {
                      if (
                        event.target.checked &&
                        bound[field] === undefined
                      ) {
                        const initial =
                          schemaType(schema) === "boolean"
                            ? typeof schema.default === "boolean"
                              ? schema.default
                              : false
                            : schema.default !== undefined
                              ? schema.default
                              : undefined;
                        if (initial !== undefined) {
                          setBound((current) => ({
                            ...current,
                            [field]: initial,
                          }));
                        }
                      }
                      setPresetFields((current) =>
                        event.target.checked
                          ? [...current, field]
                          : current.filter((candidate) => candidate !== field),
                      );
                    }}
                  />
                  <span>Preconfigurar {label}</span>
                </label>
                {selected && (
                  <SchemaInput
                    name={field}
                    schema={schema}
                    value={bound[field]}
                    suffix="preconfigurado"
                    required={(schema.minLength ?? 0) > 0}
                    onChange={(value) => setBound((current) => ({ ...current, [field]: value }))}
                  />
                )}
              </div>
            );
          })
        ) : primitiveRemoved ? (
          <p className="tool-panel-empty">
            La capacidad base ya no está disponible. Elige otra explícitamente
            para volver a vincular esta tool.
          </p>
        ) : (
          <p className="tool-panel-empty">Esta capacidad no necesita argumentos.</p>
        )}
      </fieldset>

      <button className="primary-button" disabled={pending || !primitive}>
        {pending ? "Guardando…" : tool ? "Guardar cambios" : "Crear herramienta"}
      </button>
    </form>
  );
}

function ToolRunner({
  tool,
  onClose,
  onRun,
  pending,
  result,
}: {
  tool: Tool;
  onClose: () => void;
  onRun: (arguments_: Record<string, unknown>) => void;
  pending: boolean;
  result: Record<string, unknown> | null;
}) {
  const bound = tool.bound_arguments ?? {};
  const fields = schemaEntries(tool).filter(([name]) => !(name in bound));
  const required = new Set(tool.input_schema.required ?? []);
  const [arguments_, setArguments] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(
      fields
        .filter(
          ([name, schema]) =>
            (schema.default !== undefined && schema.default !== null) ||
            (required.has(name) && schemaType(schema) === "boolean"),
        )
        .map(([name, schema]) => [
          name,
          schema.default !== undefined ? schema.default : false,
        ]),
    ),
  );

  return (
    <div className="tool-panel tool-runner-panel">
      <div className="tool-panel-heading">
        <div>
          <p className="eyebrow">Banco de prueba</p>
          <h2>{tool.name}</h2>
        </div>
        <button className="tool-icon-button" onClick={onClose} aria-label="Cerrar prueba">
          <X size={17} />
        </button>
      </div>
      <p className="tool-panel-description">{tool.description}</p>
      {Object.keys(bound).length > 0 && (
        <div className="tool-fixed-values" aria-label="Valores ya fijados">
          {Object.entries(bound).map(([name, value]) => (
            <span key={name}>{fieldLabel(name, {})}: {String(value)}</span>
          ))}
        </div>
      )}
      <form
        className="tool-run-form"
        onSubmit={(event) => {
          event.preventDefault();
          onRun(normalizedArguments(tool, arguments_));
        }}
      >
        {fields.map(([name, schema]) => (
          <SchemaInput
            key={name}
            name={name}
            schema={schema}
            required={required.has(name)}
            value={arguments_[name]}
            onChange={(value) =>
              setArguments((current) => ({ ...current, [name]: value }))
            }
          />
        ))}
        {!fields.length && <p className="tool-panel-empty">Lista para ejecutar sin datos adicionales.</p>}
        <button className="primary-button" disabled={pending}>
          <Play size={16} /> {pending ? "Ejecutando…" : "Ejecutar ahora"}
        </button>
      </form>
      {result && (
        <div className="tool-result" aria-live="polite">
          <span>Resultado</span>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

function InvocationHistory({
  tool,
  onClose,
  query,
}: {
  tool: Tool;
  onClose: () => void;
  query: ReturnType<typeof useQuery<InvocationsResponse>>;
}) {
  return (
    <div className="tool-panel tool-history-panel">
      <div className="tool-panel-heading">
        <div>
          <p className="eyebrow">Registro personal</p>
          <h2>{tool.name}</h2>
        </div>
        <button className="tool-icon-button" onClick={onClose} aria-label="Cerrar historial">
          <X size={17} />
        </button>
      </div>
      <p className="tool-panel-description">Solo aparecen tus propias ejecuciones; no se guardan argumentos ni resultados.</p>
      {query.isPending ? (
        <div className="tool-history-loading"><i /><i /><i /></div>
      ) : query.isError ? (
        <p className="inline-error">No se pudo cargar el historial.</p>
      ) : query.data?.invocations.length ? (
        <ol className="tool-invocation-list">
          {query.data.invocations.map((invocation) => (
            <li key={invocation.id} className={`invocation-${invocation.status}`}>
              <span className="invocation-signal" />
              <div>
                <strong>{STATUS_LABELS[invocation.status]}</strong>
                <small>{new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(new Date(invocation.requested_at * 1_000))}</small>
                {invocation.error_code && (
                  <small className="invocation-error">
                    {ERROR_CODE_LABELS[invocation.error_code] ?? invocation.error_code}
                  </small>
                )}
              </div>
              <code>{invocation.duration_ms === null ? "—" : `${invocation.duration_ms} ms`}</code>
            </li>
          ))}
        </ol>
      ) : (
        <p className="tool-panel-empty">Todavía no has ejecutado esta herramienta.</p>
      )}
    </div>
  );
}

function mutationMessage(error: unknown) {
  if (!error) return null;
  return error instanceof ApiError ? error.message : "No se pudo completar la operación.";
}

export function ToolsPage() {
  const client = useQueryClient();
  const [panelMode, setPanelMode] = useState<PanelMode>(null);
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [search, setSearch] = useState("");
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("all");
  const [capabilityFilter, setCapabilityFilter] = useState("all");
  const [executionResult, setExecutionResult] = useState<Record<string, unknown> | null>(null);

  const query = useQuery({
    queryKey: ["tools"],
    queryFn: () => apiFetch<ToolsResponse>("/api/herramientas"),
  });
  const tools = query.data?.herramientas ?? [];
  const primitives = tools.filter((tool) => tool.scope === "system" && tool.id === tool.primitive_id);

  const save = useMutation({
    mutationFn: ({ toolId, payload }: { toolId: string | null; payload: ToolPayload }) =>
      apiFetch<Tool>(toolId ? `/api/herramientas/${toolId}` : "/api/herramientas", {
        method: toolId ? "PUT" : "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: async () => {
      setPanelMode(null);
      setSelectedTool(null);
      await client.invalidateQueries({ queryKey: ["tools"] });
    },
  });
  const execute = useMutation({
    mutationFn: ({ tool, arguments_ }: { tool: Tool; arguments_: Record<string, unknown> }) =>
      apiFetch<ExecutionResponse>(`/api/herramientas/${tool.id}/ejecutar`, {
        method: "POST",
        body: JSON.stringify({ arguments: arguments_ }),
      }),
    onSuccess: async ({ result }) => {
      setExecutionResult(result);
      await client.invalidateQueries({ queryKey: ["tools"] });
    },
  });
  const toggle = useMutation({
    mutationFn: (tool: Tool) =>
      apiFetch<Tool>(`/api/herramientas/${tool.id}/estado`, {
        method: "POST",
        body: JSON.stringify({ enabled: !tool.enabled }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["tools"] }),
  });
  const duplicate = useMutation({
    mutationFn: (tool: Tool) =>
      apiFetch<Tool>(`/api/herramientas/${tool.id}/duplicar`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["tools"] }),
  });
  const historyQuery = useQuery<InvocationsResponse>({
    queryKey: ["tool-invocations", selectedTool?.id],
    queryFn: () =>
      apiFetch<InvocationsResponse>(
        `/api/herramientas/${selectedTool?.id}/invocaciones?limite=50`,
      ),
    enabled: panelMode === "history" && selectedTool !== null,
  });

  const filteredTools = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase("es");
    return tools.filter((tool) => {
      const matchesText =
        !normalized ||
        `${tool.name} ${tool.description} ${tool.primitive_id}`
          .toLocaleLowerCase("es")
          .includes(normalized);
      const matchesScope = scopeFilter === "all" || tool.scope === scopeFilter;
      const matchesCapability =
        capabilityFilter === "all" || tool.primitive_id === capabilityFilter;
      return matchesText && matchesScope && matchesCapability;
    });
  }, [capabilityFilter, scopeFilter, search, tools]);

  const totalInvocations = tools.reduce(
    (total, tool) => total + (tool.usage ?? EMPTY_USAGE).total,
    0,
  );
  const succeeded = tools.reduce(
    (total, tool) => total + (tool.usage ?? EMPTY_USAGE).succeeded,
    0,
  );
  const completed = tools.reduce((total, tool) => {
    const usage = tool.usage ?? EMPTY_USAGE;
    return total + usage.succeeded + usage.failed + usage.denied;
  }, 0);
  const error = mutationMessage(
    save.error ?? execute.error ?? toggle.error ?? duplicate.error,
  );
  const closePanel = () => {
    setPanelMode(null);
    setSelectedTool(null);
    setExecutionResult(null);
  };

  return (
    <section className="page tools-page tool-workbench-page">
      <header className="page-header tool-workbench-header">
        <div>
          <p className="eyebrow">Patchbay de capacidades</p>
          <h1>Herramientas</h1>
          <p>Combina primitivas revisadas, fija contexto y observa cada ejecución sin exponer datos sensibles.</p>
        </div>
        <button
          className="primary-button tool-builder-trigger"
          onClick={() => {
            setSelectedTool(null);
            setPanelMode("editor");
            setExecutionResult(null);
          }}
        >
          <Plus size={18} /> Crear tool
        </button>
      </header>

      <div className="tool-signal-strip" aria-label="Estado del catálogo">
        <span><i className="signal-live" /><strong>{tools.filter((tool) => tool.enabled).length}</strong> activas</span>
        <span><Activity size={14} /><strong>{totalInvocations}</strong> ejecuciones</span>
        <span><ShieldCheck size={14} /><strong>{completed ? Math.round((succeeded / completed) * 100) : "—"}%</strong> éxito</span>
        <span><SlidersHorizontal size={14} /><strong>{primitives.length}</strong> primitivas</span>
      </div>

      <div className="tool-toolbar">
        <label className="tool-search-field">
          <Search size={16} />
          <span className="sr-only">Buscar herramientas</span>
          <input aria-label="Buscar herramientas" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar por nombre o capacidad…" />
        </label>
        <label>
          <span className="sr-only">Filtrar por alcance</span>
          <select aria-label="Filtrar por alcance" value={scopeFilter} onChange={(event) => setScopeFilter(event.target.value as ScopeFilter)}>
            <option value="all">Todos los alcances</option>
            <option value="system">Base</option>
            <option value="personal">Personales</option>
            <option value="lab">Lab</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Filtrar por capacidad</span>
          <select aria-label="Filtrar por capacidad" value={capabilityFilter} onChange={(event) => setCapabilityFilter(event.target.value)}>
            <option value="all">Todas las capacidades</option>
            {primitives.map((primitive) => <option key={primitive.id} value={primitive.id}>{primitive.name}</option>)}
          </select>
        </label>
      </div>

      {error && <p className="inline-error" role="alert">{error}</p>}

      <div className={`tool-workbench${panelMode ? " has-panel" : ""}`}>
        <div className="tool-catalog-pane">
          {query.isPending ? (
            <div className="tool-card-grid"><i className="resource-skeleton" /><i className="resource-skeleton" /><i className="resource-skeleton" /></div>
          ) : query.isError ? (
            <div className="tool-empty-state"><Wrench size={28} /><p>No se pudo abrir el catálogo.</p><button className="reject-button" onClick={() => query.refetch()}>Reintentar</button></div>
          ) : filteredTools.length ? (
            <ul className="tool-card-grid" aria-label="Catálogo de herramientas">
              {filteredTools.map((tool) => {
                const usage = tool.usage ?? EMPTY_USAGE;
                return (
                  <li key={tool.id} className={`tool-module${tool.enabled ? "" : " is-disabled"}`}>
                    <span className={`tool-module-rail effect-${tool.effects.includes("filesystem:write") ? "write" : "read"}`} />
                    <div className="tool-module-heading">
                      <span className="tool-module-icon">{toolIcon(tool)}</span>
                      <div>
                        <span className={`scope-badge scope-${tool.scope}`}>{SCOPE_LABELS[tool.scope]}</span>
                        <code>{tool.kind === "script" ? `guion · ${tool.lineas ?? 0} líneas` : tool.primitive_id}</code>
                      </div>
                    </div>
                    <h2>{tool.name}</h2>
                    <p>{tool.description}</p>
                    <div className="tool-module-usage">
                      <span><strong>{usage.total}</strong> usos</span>
                      <span><strong>{usage.success_rate ?? "—"}%</strong> éxito</span>
                      <span><strong>{usage.average_duration_ms ?? "—"}</strong> ms</span>
                    </div>
                    <div className="tool-permissions"><ShieldCheck size={13} />{tool.permissions.length ? tool.permissions.join(" · ") : "Sin permisos especiales"}</div>
                    <div className="tool-module-actions">
                      <button disabled={!tool.enabled} onClick={() => { setSelectedTool(tool); setPanelMode("runner"); setExecutionResult(null); }} aria-label={`Probar ${tool.name}`}><Play size={14} /> Probar</button>
                      <button onClick={() => { setSelectedTool(tool); setPanelMode("history"); }} aria-label={`Historial ${tool.name}`}><History size={14} /> Historial</button>
                      <div className="tool-module-menu">
                        {tool.editable && <button onClick={() => { setSelectedTool(tool); setPanelMode("editor"); }} aria-label={`Editar ${tool.name}`} title="Editar"><Pencil size={14} /></button>}
                        {tool.duplicable && <button disabled={duplicate.isPending} onClick={() => duplicate.mutate(tool)} aria-label={`Duplicar ${tool.name}`} title="Duplicar"><Copy size={14} /></button>}
                        {(tool.editable || tool.kind === "script") && <button disabled={toggle.isPending} onClick={() => toggle.mutate(tool)} aria-label={`${tool.enabled ? "Desactivar" : "Activar"} ${tool.name}`} title={tool.enabled ? "Desactivar" : "Activar"}>{tool.enabled ? <ToggleRight size={17} /> : <ToggleLeft size={17} />}</button>}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="tool-empty-state"><Search size={27} /><p>Ninguna herramienta coincide con estos filtros.</p></div>
          )}
        </div>

        {panelMode === "editor" && (
          <ToolEditor key={selectedTool?.id ?? "new"} tool={selectedTool} primitives={primitives} onClose={closePanel} pending={save.isPending} onSave={(toolId, payload) => save.mutate({ toolId, payload })} />
        )}
        {panelMode === "runner" && selectedTool && (
          <ToolRunner key={selectedTool.id} tool={selectedTool} onClose={closePanel} pending={execute.isPending} result={executionResult} onRun={(arguments_) => execute.mutate({ tool: selectedTool, arguments_ })} />
        )}
        {panelMode === "history" && selectedTool && (
          <InvocationHistory tool={selectedTool} onClose={closePanel} query={historyQuery} />
        )}
      </div>
    </section>
  );
}
