import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, KeyRound, MessageCircle, Mic2, ShieldCheck, Wrench } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError, apiFetch } from "../lib/api";

type Provider = "anthropic" | "groq" | "antigravity";
// Antigravity se autentica con la sesión de Google de la CLI del usuario:
// no tiene clave que guardar aquí.
type KeyedProvider = "anthropic" | "groq";
type ChatProvider = "anthropic" | "antigravity";
type CredentialSource = "personal" | "system" | "none";

interface AISettings {
  chat_provider: ChatProvider;
  chat_model: string;
  tools_provider: KeyedProvider;
  tools_model: string;
  speech_provider: "groq";
  speech_model: string;
  agent_provider: "anthropic";
  agent_model: string;
  credentials: Record<KeyedProvider, { configured: boolean; source: CredentialSource }>;
  effective: Record<string, { provider?: Provider; model?: string; available: boolean; fallback: boolean }>;
}

type EditableSettings = Pick<
  AISettings,
  | "chat_provider"
  | "chat_model"
  | "tools_provider"
  | "tools_model"
  | "speech_provider"
  | "speech_model"
  | "agent_provider"
  | "agent_model"
>;

const fallbackSettings: EditableSettings = {
  chat_provider: "anthropic",
  chat_model: "claude-haiku-4-5",
  tools_provider: "anthropic",
  tools_model: "claude-haiku-4-5",
  speech_provider: "groq",
  speech_model: "whisper-large-v3-turbo",
  agent_provider: "anthropic",
  agent_model: "claude-sonnet-5",
};

const sourceLabel: Record<CredentialSource, string> = {
  personal: "Clave personal",
  system: "Clave del servidor",
  none: "Sin clave",
};

export function SettingsPage() {
  const client = useQueryClient();
  const [form, setForm] = useState<EditableSettings>(fallbackSettings);
  const [anthropicKey, setAnthropicKey] = useState("");
  const [groqKey, setGroqKey] = useState("");
  const [clearAnthropic, setClearAnthropic] = useState(false);
  const [clearGroq, setClearGroq] = useState(false);
  const [saved, setSaved] = useState("");
  const query = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => apiFetch<AISettings>("/api/configuracion/ia"),
  });

  useEffect(() => {
    if (!query.data) return;
    const {
      chat_provider,
      tools_provider,
      tools_model,
      speech_provider,
      speech_model,
      agent_provider,
      agent_model,
    } = query.data;
    setForm({
      chat_provider,
      chat_model: "claude-haiku-4-5",
      tools_provider,
      tools_model,
      speech_provider,
      speech_model,
      agent_provider,
      agent_model,
    });
  }, [query.data]);

  const save = useMutation({
    mutationFn: () =>
      apiFetch<AISettings>("/api/configuracion/ia", {
        method: "PUT",
        body: JSON.stringify({
          ...form,
          ...(anthropicKey ? { anthropic_api_key: anthropicKey } : {}),
          ...(groqKey ? { groq_api_key: groqKey } : {}),
          clear_anthropic_api_key: clearAnthropic,
          clear_groq_api_key: clearGroq,
        }),
      }),
    onSuccess: (data) => {
      client.setQueryData(["ai-settings"], data);
      setAnthropicKey("");
      setGroqKey("");
      setClearAnthropic(false);
      setClearGroq(false);
      setSaved("Configuración aplicada.");
    },
  });

  const update = <Key extends keyof EditableSettings>(
    key: Key,
    value: EditableSettings[Key],
  ) => setForm((current) => ({ ...current, [key]: value }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSaved("");
    save.mutate();
  };
  const error = save.error instanceof ApiError
    ? save.error.message
    : save.error
      ? "No se pudo guardar la configuración."
      : null;

  return (
    <section className="page settings-page">
      <header className="page-header settings-header">
        <div>
          <p className="eyebrow">Tu infraestructura</p>
          <h1>Configuración</h1>
          <p>Elige quién piensa en cada parte de Vibi. Tus claves personales se cifran y nunca vuelven a mostrarse.</p>
        </div>
        <span className="settings-security"><ShieldCheck size={16} /> Credenciales aisladas</span>
      </header>

      {query.isPending ? (
        <div className="settings-loading"><i /><i /></div>
      ) : query.isError ? (
        <p className="inline-error">No se pudo cargar tu configuración.</p>
      ) : (
        <form className="settings-form" onSubmit={submit}>
          <section className="settings-section credentials-section">
            <div className="settings-section-heading">
              <span><KeyRound size={20} /></span>
              <div><p className="eyebrow">Credenciales</p><h2>Claves de proveedor</h2></div>
            </div>
            <div className="credential-grid">
              {(["anthropic", "groq"] as const).map((provider) => {
                const credential = query.data.credentials[provider];
                const clear = provider === "anthropic" ? clearAnthropic : clearGroq;
                return (
                  <label key={provider} className="credential-card">
                    <span className="credential-title">
                      <strong>{provider === "anthropic" ? "Anthropic" : "Groq"}</strong>
                      <small className={`credential-${clear ? "none" : credential.source}`}>
                        {clear ? "Se eliminará" : sourceLabel[credential.source]}
                      </small>
                    </span>
                    <input
                      type="password"
                      autoComplete="off"
                      value={provider === "anthropic" ? anthropicKey : groqKey}
                      onChange={(event) => {
                        if (provider === "anthropic") {
                          setAnthropicKey(event.target.value);
                          setClearAnthropic(false);
                        } else {
                          setGroqKey(event.target.value);
                          setClearGroq(false);
                        }
                      }}
                      placeholder={credential.configured ? "••••••••  reemplazar clave" : "Pegar API key"}
                    />
                    {credential.source === "personal" && (
                      <button
                        type="button"
                        className="text-button credential-remove"
                        onClick={() => provider === "anthropic" ? setClearAnthropic(true) : setClearGroq(true)}
                      >
                        Quitar clave personal
                      </button>
                    )}
                  </label>
                );
              })}
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-heading">
              <span><Bot size={20} /></span>
              <div><p className="eyebrow">Rutas de IA</p><h2>Modelos por función</h2></div>
            </div>
            <div className="lane-grid">
              <div className="lane-card">
                <span className="lane-icon"><MessageCircle size={19} /></span>
                <div><h3>Conversación</h3><p>Sesión persistente con terminal y tools.</p></div>
                <label>Runtime<select value={form.chat_provider} onChange={(event) => update("chat_provider", event.target.value as ChatProvider)}><option value="anthropic">Claude Code</option><option value="antigravity">Antigravity (Gemini)</option></select></label>
                <label>Modelo<input value={form.chat_provider === "antigravity" ? "el de tu CLI de Antigravity" : "claude-haiku-4-5"} disabled /></label>
                <small className="lane-note">
                  {form.chat_provider === "antigravity"
                    ? "Usa tu sesión de Google en la CLI agy: más rápido y sin gastar API, con las tools de Vibi por MCP. Si falla, responde Claude."
                    : "Thinking se controla desde el chat."}
                </small>
              </div>
              <div className="lane-card lane-featured">
                <span className="lane-icon"><Wrench size={19} /></span>
                <div><h3>Tools</h3><p>Intención, argumentos y lectura de documentos.</p></div>
                <label>Proveedor<select value={form.tools_provider} onChange={(event) => update("tools_provider", event.target.value as KeyedProvider)}><option value="anthropic">Anthropic</option><option value="groq">Groq</option></select></label>
                <label>Modelo<input list="tool-models" value={form.tools_model} onChange={(event) => update("tools_model", event.target.value)} /></label>
                <small className="lane-note">Recomendado: Claude Haiku 4.5</small>
              </div>
              <div className="lane-card">
                <span className="lane-icon"><Mic2 size={19} /></span>
                <div><h3>Voz</h3><p>Transcripción de audio antes del enrutado.</p></div>
                <label>Proveedor<select value="groq" disabled><option>Groq</option></select></label>
                <label>Modelo<input list="speech-models" value={form.speech_model} onChange={(event) => update("speech_model", event.target.value)} /></label>
              </div>
              <div className="lane-card">
                <span className="lane-icon"><Bot size={19} /></span>
                <div><h3>Agente</h3><p>Planificación y ejecución sobre proyectos.</p></div>
                <label>Proveedor<select value="anthropic" disabled><option>Anthropic</option></select></label>
                <label>Modelo<select value={form.agent_model} onChange={(event) => update("agent_model", event.target.value)}><option value="claude-sonnet-5">Claude Sonnet 5</option><option value="claude-fable-5">Claude Fable 5</option><option value="claude-opus-4-8">Claude Opus 4.8</option><option value="claude-haiku-4-5">Claude Haiku 4.5</option></select></label>
              </div>
            </div>
          </section>

          <datalist id="tool-models"><option value="claude-haiku-4-5" /><option value="llama-3.3-70b-versatile" /></datalist>
          <datalist id="speech-models"><option value="whisper-large-v3-turbo" /></datalist>
          {saved && <p className="success-message" role="status">{saved}</p>}
          {error && <p className="inline-error" role="alert">{error}</p>}
          {query.data.effective.tools?.fallback && <p className="settings-warning">Tools está usando Groq temporalmente porque no hay una clave de Anthropic disponible.</p>}
          <button className="primary-button settings-save" disabled={save.isPending}>
            {save.isPending ? "Aplicando…" : "Guardar y aplicar"}
          </button>
        </form>
      )}
    </section>
  );
}
