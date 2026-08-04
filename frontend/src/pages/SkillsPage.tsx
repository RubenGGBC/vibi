import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpenCheck,
  Boxes,
  Check,
  Circle,
  Copy,
  Download,
  FlaskConical,
  Pencil,
  Plus,
  Power,
  Sparkles,
  X,
} from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { ApiError, apiFetch } from "../lib/api";
import type { Skill, SkillRun, SkillsResponse } from "../types";

interface SkillDraft {
  name: string;
  slug: string;
  description: string;
  instructions: string;
  examples: string;
  toolIds: string[];
  scope: "personal" | "lab";
}

interface ExportedSkill {
  filename: string;
  content: string;
}

const emptyDraft: SkillDraft = {
  name: "",
  slug: "",
  description: "",
  instructions: "",
  examples: "",
  toolIds: [],
  scope: "personal",
};

const slugify = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);

const errorMessage = (error: unknown) =>
  error instanceof ApiError ? error.message : "No se pudo completar la operación.";

const draftFromSkill = (skill: Skill): SkillDraft => ({
  name: skill.name,
  slug: skill.slug,
  description: skill.description,
  instructions: skill.instructions,
  examples: skill.examples.join("\n"),
  toolIds: skill.tool_ids,
  scope: skill.scope,
});

export function SkillsPage() {
  const client = useQueryClient();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<SkillDraft>(emptyDraft);
  const [playSkill, setPlaySkill] = useState<Skill | null>(null);
  const [playInput, setPlayInput] = useState("");
  const [playResult, setPlayResult] = useState<SkillRun | null>(null);
  const [exported, setExported] = useState<ExportedSkill | null>(null);

  const query = useQuery({
    queryKey: ["skills"],
    queryFn: () => apiFetch<SkillsResponse>("/api/skills"),
  });

  const resetEditor = () => {
    setDraft(emptyDraft);
    setEditingId(null);
    setEditorOpen(false);
  };

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: draft.name,
        slug: draft.slug || slugify(draft.name),
        description: draft.description,
        instructions: draft.instructions,
        examples: draft.examples
          .split("\n")
          .map((example) => example.trim())
          .filter(Boolean),
        tool_ids: draft.toolIds,
        scope: draft.scope,
      };
      return apiFetch<Skill>(
        editingId ? `/api/skills/${editingId}` : "/api/skills",
        { method: editingId ? "PUT" : "POST", body: JSON.stringify(payload) },
      );
    },
    onSuccess: async () => {
      resetEditor();
      await client.invalidateQueries({ queryKey: ["skills"] });
    },
  });

  const status = useMutation({
    mutationFn: (skill: Skill) =>
      apiFetch<Skill>(`/api/skills/${skill.id}/estado`, {
        method: "POST",
        body: JSON.stringify({ enabled: !skill.enabled }),
      }),
    onSuccess: async () => client.invalidateQueries({ queryKey: ["skills"] }),
  });

  const duplicate = useMutation({
    mutationFn: (skill: Skill) =>
      apiFetch<Skill>(`/api/skills/${skill.id}/duplicar`, { method: "POST" }),
    onSuccess: async () => client.invalidateQueries({ queryKey: ["skills"] }),
  });

  const run = useMutation({
    mutationFn: () =>
      apiFetch<SkillRun>(`/api/skills/${playSkill?.id}/probar`, {
        method: "POST",
        body: JSON.stringify({ input: playInput }),
      }),
    onSuccess: setPlayResult,
  });

  const exportSkill = useMutation({
    mutationFn: (skill: Skill) =>
      apiFetch<ExportedSkill>(`/api/skills/${skill.id}/exportar`),
    onSuccess: setExported,
  });

  const localStages = useMemo(
    () => [
      {
        label: "Identidad",
        complete: draft.name.trim().length >= 3 && draft.description.trim().length >= 20,
      },
      { label: "Instrucciones", complete: draft.instructions.trim().length >= 40 },
      { label: "Capacidades", complete: draft.toolIds.length > 0, optional: true },
      {
        label: "Ejemplos",
        complete: draft.examples.split("\n").some((line) => line.trim()),
      },
    ],
    [draft],
  );
  const ready = localStages.every((stage) => stage.complete || stage.optional);
  const currentSlug = draft.slug || slugify(draft.name);
  const mutationError =
    save.error ?? status.error ?? duplicate.error ?? run.error ?? exportSkill.error;

  const openNew = () => {
    setDraft(emptyDraft);
    setEditingId(null);
    setEditorOpen(true);
  };

  const openEdit = (skill: Skill) => {
    setDraft(draftFromSkill(skill));
    setEditingId(skill.id);
    setEditorOpen(true);
  };

  const openPlayground = (skill: Skill) => {
    setPlaySkill(skill);
    setPlayInput(skill.examples[0] ?? "");
    setPlayResult(null);
    setExported(null);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  return (
    <section className="page skills-page">
      <header className="page-header resource-header skill-studio-header">
        <div>
          <p className="eyebrow">Procedimientos reutilizables</p>
          <h1>Skill Studio</h1>
          <p>
            Escribe cómo debe trabajar Morgana, limita qué capacidades puede usar y
            ensaya el resultado antes de activarlo.
          </p>
        </div>
        <button className="primary-button" onClick={openNew}>
          <Plus size={18} /> Nueva skill
        </button>
      </header>

      {query.isError ? (
        <div className="skill-load-error">
          <p>No se pudo abrir Skill Studio. Vuelve a intentarlo.</p>
          <button className="reject-button" onClick={() => query.refetch()}>
            Reintentar
          </button>
        </div>
      ) : (
        <div className={`skill-workbench${editorOpen || playSkill ? " is-open" : ""}`}>
          <div className="skill-catalog-pane">
            <div className="skill-catalog-intro">
              <p>
                <strong>{query.data?.summary.active ?? 0}</strong> activas
                <span aria-hidden="true"> · </span>
                <strong>{query.data?.summary.drafts ?? 0}</strong> borradores
              </p>
              <code>/skill nombre tu petición</code>
            </div>

            {query.isPending ? (
              <div className="skill-card-list" aria-label="Cargando skills">
                <i className="resource-skeleton" />
                <i className="resource-skeleton" />
              </div>
            ) : query.data?.skills.length ? (
              <ul className="skill-card-list" aria-label="Skills disponibles">
                {query.data.skills.map((skill) => (
                  <li key={skill.id} className={`skill-card${skill.enabled ? " is-active" : ""}`}>
                    <div className="skill-card-meta">
                      <span className={skill.enabled ? "skill-state active" : "skill-state"}>
                        {skill.enabled ? "Activa" : "Borrador"}
                      </span>
                      <span>v{skill.version}</span>
                      <span>{skill.scope === "lab" ? "Lab" : "Personal"}</span>
                    </div>
                    <h2>{skill.name}</h2>
                    <code>/skill {skill.slug}</code>
                    <p>{skill.description}</p>
                    <div className="skill-capability-row">
                      {skill.tools.length ? (
                        skill.tools.map((tool) => <span key={tool.id}>{tool.id}</span>)
                      ) : (
                        <span>Solo instrucciones</span>
                      )}
                    </div>
                    <div className="skill-card-actions">
                      <button aria-label={`Probar ${skill.name}`} onClick={() => openPlayground(skill)}>
                        <FlaskConical size={15} /> Probar
                      </button>
                      <button aria-label={`Editar ${skill.name}`} onClick={() => openEdit(skill)}>
                        <Pencil size={15} /> Editar
                      </button>
                      <button
                        aria-label={`Exportar ${skill.name}`}
                        onClick={() => exportSkill.mutate(skill)}
                      >
                        <Download size={15} /> Exportar
                      </button>
                      <button
                        aria-label={`Duplicar ${skill.name}`}
                        onClick={() => duplicate.mutate(skill)}
                      >
                        <Copy size={15} /> Duplicar
                      </button>
                      <button
                        className="skill-power"
                        aria-label={`${skill.enabled ? "Desactivar" : "Activar"} ${skill.name}`}
                        disabled={status.isPending}
                        onClick={() => status.mutate(skill)}
                      >
                        <Power size={15} /> {skill.enabled ? "Desactivar" : "Activar"}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="skill-empty">
                <Sparkles size={24} />
                <p>Aún no has creado ninguna skill.</p>
                <button className="text-button" onClick={openNew}>Crear la primera</button>
              </div>
            )}
          </div>

          {editorOpen && (
            <form className="skill-editor-pane" onSubmit={submit}>
              <div className="skill-pane-title">
                <div>
                  <p className="eyebrow">{editingId ? "Nueva versión" : "Nuevo manifiesto"}</p>
                  <h2>{editingId ? "Editar skill" : "Construir skill"}</h2>
                </div>
                <button type="button" className="icon-button" aria-label="Cerrar editor" onClick={resetEditor}>
                  <X size={18} />
                </button>
              </div>

              <ol className="skill-binding">
                <li className={localStages[0].complete ? "complete" : ""}>
                  <span className="binding-node">{localStages[0].complete ? <Check size={13} /> : <Circle size={10} />}</span>
                  <div className="skill-editor-section">
                    <h3>Identidad</h3>
                    <label>Nombre<input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value, slug: editingId ? current.slug : slugify(event.target.value) }))} /></label>
                    <label>Comando<input value={currentSlug} maxLength={64} onChange={(event) => setDraft((current) => ({ ...current, slug: slugify(event.target.value) }))} /></label>
                    <label>Descripción<textarea value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} /></label>
                  </div>
                </li>
                <li className={localStages[1].complete ? "complete" : ""}>
                  <span className="binding-node">{localStages[1].complete ? <Check size={13} /> : <Circle size={10} />}</span>
                  <div className="skill-editor-section">
                    <h3>Instrucciones</h3>
                    <label>Instrucciones<textarea className="skill-instructions" value={draft.instructions} onChange={(event) => setDraft((current) => ({ ...current, instructions: event.target.value }))} placeholder="Define el procedimiento, los límites y la forma de la respuesta." /></label>
                  </div>
                </li>
                <li className={localStages[2].complete ? "complete optional" : "optional"}>
                  <span className="binding-node">{localStages[2].complete ? <Check size={13} /> : <Boxes size={12} />}</span>
                  <fieldset className="skill-editor-section capability-picker">
                    <legend>Capacidades <small>Opcional</small></legend>
                    {query.data?.available_tools.filter((tool) => tool.enabled).map((tool) => (
                      <label key={tool.id}>
                        <input type="checkbox" checked={draft.toolIds.includes(tool.id)} onChange={() => setDraft((current) => ({ ...current, toolIds: current.toolIds.includes(tool.id) ? current.toolIds.filter((id) => id !== tool.id) : [...current.toolIds, tool.id].slice(0, 4) }))} />
                        <span><strong>{tool.name}</strong><small>{tool.description}</small><code>{tool.permissions.join(" · ") || "sin permisos especiales"}</code></span>
                      </label>
                    ))}
                  </fieldset>
                </li>
                <li className={localStages[3].complete ? "complete" : ""}>
                  <span className="binding-node">{localStages[3].complete ? <Check size={13} /> : <Circle size={10} />}</span>
                  <div className="skill-editor-section">
                    <h3>Ejemplos</h3>
                    <label>Ejemplos<textarea value={draft.examples} onChange={(event) => setDraft((current) => ({ ...current, examples: event.target.value }))} placeholder="Una petición por línea" /></label>
                    <label>Alcance<select value={draft.scope} onChange={(event) => setDraft((current) => ({ ...current, scope: event.target.value as SkillDraft["scope"] }))}><option value="personal">Personal</option><option value="lab">Laboratorio</option></select></label>
                  </div>
                </li>
              </ol>

              <div className={`skill-readiness${ready ? " ready" : ""}`} role="status">
                <BookOpenCheck size={20} />
                <div><strong>{ready ? "Lista para activar" : "Manifiesto en progreso"}</strong><span>{ready ? `Invócala con /skill ${currentSlug}` : "Completa identidad, instrucciones y un ejemplo."}</span></div>
              </div>
              {mutationError && <p className="inline-error" role="alert">{errorMessage(mutationError)}</p>}
              <button className="primary-button" disabled={save.isPending}>
                {save.isPending ? "Guardando…" : editingId ? "Guardar nueva versión" : "Guardar borrador"}
              </button>
            </form>
          )}

          {playSkill && !editorOpen && (
            <section className="skill-playground skill-editor-pane">
              <div className="skill-pane-title">
                <div><p className="eyebrow">Banco de pruebas</p><h2>{playSkill.name}</h2></div>
                <button className="icon-button" aria-label="Cerrar banco de pruebas" onClick={() => setPlaySkill(null)}><X size={18} /></button>
              </div>
              <p>Prueba el manifiesto actual, incluso si sigue en borrador.</p>
              <label>Petición de prueba<textarea value={playInput} onChange={(event) => setPlayInput(event.target.value)} /></label>
              <button className="primary-button" disabled={!playInput.trim() || run.isPending} onClick={() => run.mutate()}>{run.isPending ? "Ejecutando…" : "Ejecutar prueba"}</button>
              {run.error && <p className="inline-error" role="alert">{errorMessage(run.error)}</p>}
              {playResult && <div className="skill-run-result" aria-live="polite"><p className="eyebrow">Respuesta</p><p>{playResult.response}</p>{playResult.tool_runs.map((toolRun) => <code key={toolRun.tool_id}>{toolRun.tool_id} · {toolRun.status}</code>)}</div>}
            </section>
          )}
        </div>
      )}

      {exported && (
        <section className="skill-export-preview" aria-label="Exportación de skill">
          <div className="skill-pane-title"><div><p className="eyebrow">SKILL.md portable</p><h2>{exported.filename}</h2></div><button className="icon-button" aria-label="Cerrar exportación" onClick={() => setExported(null)}><X size={18} /></button></div>
          <pre>{exported.content}</pre>
        </section>
      )}
    </section>
  );
}
