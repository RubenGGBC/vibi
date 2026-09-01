import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Brain,
  Check,
  Download,
  File,
  RotateCcw,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { MarkdownContent } from "./MarkdownContent";
import { MessageComposer } from "./MessageComposer";
import { ApiError, apiBlob, apiFetch } from "../lib/api";
import {
  chatRuntimeKey,
  conversationKey,
  mergeConversationState,
} from "../lib/conversation";
import type {
  ChatRuntimeState,
  ConversationState,
  MessageResponse,
  Tool,
  UserFile,
} from "../types";

/**
 * Una línea del hilo.
 *
 * `error` no viene del servidor: lo pone esta pantalla cuando el envío se cae,
 * y antes se colaba como una respuesta más de Vibi. Separarlo es lo que permite
 * que se lea como lo que es —una línea de fallo— sin fingir que ella lo dijo.
 */
type ChatItem =
  | {
      id: string;
      kind: "user" | "assistant" | "error";
      text: string;
      at: number;
      clientRef?: string;
    }
  | { id: string; kind: "files"; files: UserFile[]; at: number };

/** La marca del canalón: quién habla, en un carácter. */
const MARCAS: Record<ChatItem["kind"], string> = {
  user: "›",
  assistant: "✦",
  error: "!",
  files: "≡",
};

const RELOJ = new Intl.DateTimeFormat("es-ES", {
  hour: "2-digit",
  minute: "2-digit",
});

/** El servidor cuenta en segundos; `Intl`, en milisegundos. */
const horaDe = (epoch: number) => RELOJ.format(new Date(epoch * 1000));

const ahora = () => Date.now() / 1000;

interface ToolsResponse {
  herramientas: Tool[];
}

interface ThinkingResponse {
  conversation_id: string;
  thinking_enabled: boolean;
}

const downloadFile = async (file: UserFile) => {
  const blob = await apiBlob(file.download_url);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

export function ChatPanel() {
  const queryClient = useQueryClient();
  const [transientItems, setTransientItems] = useState<ChatItem[]>([]);
  const [resetError, setResetError] = useState<string | null>(null);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [attachedToolIds, setAttachedToolIds] = useState<string[]>([]);
  const conversationId = useRef<string | null>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const history = useQuery<ConversationState>({
    queryKey: conversationKey,
    queryFn: () =>
      apiFetch<ConversationState>("/api/conversations/active/messages?limit=50"),
    structuralSharing: (current, incoming) =>
      mergeConversationState(
        current as ConversationState | undefined,
        incoming as ConversationState,
      ),
  });
  const runtime = useQuery<ChatRuntimeState | null>({
    queryKey: chatRuntimeKey,
    queryFn: async () => null,
    enabled: false,
    initialData: null,
  });
  const toolsQuery = useQuery<ToolsResponse>({
    queryKey: ["tools"],
    queryFn: () => apiFetch<ToolsResponse>("/api/herramientas"),
  });
  const send = useMutation({
    mutationFn: ({
      texto,
      clientRef,
      toolIds,
    }: {
      texto: string;
      clientRef: string;
      toolIds: string[];
    }) =>
      apiFetch<MessageResponse>("/api/mensaje", {
        method: "POST",
        body: JSON.stringify({
          texto,
          client_ref: clientRef,
          tool_ids: toolIds,
        }),
      }),
  });
  const reset = useMutation({
    mutationFn: () =>
      apiFetch<ConversationState>("/api/conversations/reset", { method: "POST" }),
  });
  const thinking = useMutation<
    ThinkingResponse,
    Error,
    boolean,
    { previous?: ConversationState }
  >({
    mutationFn: (enabled) =>
      apiFetch<ThinkingResponse>("/api/conversations/active/thinking", {
        method: "POST",
        body: JSON.stringify({ enabled }),
      }),
    onMutate: async (enabled) => {
      await queryClient.cancelQueries({ queryKey: conversationKey });
      const previous = queryClient.getQueryData<ConversationState>(conversationKey);
      queryClient.setQueryData<ConversationState>(conversationKey, (current) =>
        current ? { ...current, thinking_enabled: enabled } : current,
      );
      return { previous };
    },
    onError: (_error, _enabled, context) => {
      if (context?.previous) {
        queryClient.setQueryData(conversationKey, context.previous);
      }
    },
  });

  useEffect(() => {
    const nextId = history.data?.conversation_id;
    if (!nextId) return;
    if (conversationId.current && conversationId.current !== nextId) {
      setTransientItems([]);
      queryClient.setQueryData<ChatRuntimeState | null>(chatRuntimeKey, null);
    }
    conversationId.current = nextId;
  }, [history.data?.conversation_id]);

  const messages = history.data?.messages ?? [];
  const reconciledRefs = new Set(
    messages.flatMap((message) => (message.client_ref ? [message.client_ref] : [])),
  );
  const serverItems: ChatItem[] = messages.map((message) => ({
    id: `message-${message.id}`,
    kind: message.role,
    text: message.content,
    at: message.created_at,
  }));
  const visibleTransientItems = transientItems.filter(
    (item) =>
      !("clientRef" in item) ||
      !item.clientRef ||
      !reconciledRefs.has(item.clientRef),
  );
  const items = [...serverItems, ...visibleTransientItems];
  const availableTools = (toolsQuery.data?.herramientas ?? [])
    .filter((tool) => tool.enabled)
    .sort((left, right) => left.name.localeCompare(right.name, "es"));
  const attachedTools = attachedToolIds.flatMap((toolId) => {
    const tool = availableTools.find((candidate) => candidate.id === toolId);
    return tool ? [tool] : [];
  });
  const thinkingEnabled = history.data?.thinking_enabled ?? false;
  const liveRuntime =
    runtime.data?.conversation_id === history.data?.conversation_id
      ? runtime.data
      : null;

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const conversation = conversationRef.current;
      if (conversation) conversation.scrollTop = conversation.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [items, liveRuntime?.label, liveRuntime?.text, send.isPending]);

  const submit = async (text: string) => {
    const clientRef = crypto.randomUUID();
    const toolIds = [...attachedToolIds];
    setTransientItems((current) => [
      ...current,
      { id: clientRef, kind: "user", text, clientRef, at: ahora() },
    ]);
    if (history.data?.conversation_id) {
      const initialRuntime: ChatRuntimeState = {
        conversation_id: history.data.conversation_id,
        turn_id: clientRef,
        label: "Conectando con Claude Code…",
        text: "",
        boundaries: 0,
        fase: "arranque",
        // Todavía no hay herramienta: el turno acaba de salir de aquí.
        herramienta: "",
      };
      queryClient.setQueryData<ChatRuntimeState | null>(
        chatRuntimeKey,
        () => initialRuntime,
      );
    }
    try {
      const result = await send.mutateAsync({ texto: text, clientRef, toolIds });
      setAttachedToolIds([]);
      setToolsOpen(false);
      await history.refetch();
      if (result.via === "herramienta" && result.artifacts.length) {
        setTransientItems((current) => [
          ...current,
          {
            id: `${clientRef}-files`,
            kind: "files",
            files: result.artifacts,
            at: ahora(),
          },
        ]);
      }
    } catch (reason) {
      setTransientItems((current) => [
        ...current,
        {
          id: `${clientRef}-error`,
          kind: "error",
          at: ahora(),
          text:
            reason instanceof ApiError
              ? reason.message
              : "No se pudo enviar el mensaje. Vuelve a intentarlo.",
        },
      ]);
    } finally {
      queryClient.setQueryData<ChatRuntimeState | null>(
        chatRuntimeKey,
        (current) => current?.turn_id === clientRef ? null : current ?? null,
      );
    }
  };

  const toggleTool = (toolId: string) => {
    setAttachedToolIds((current) =>
      current.includes(toolId)
        ? current.filter((candidate) => candidate !== toolId)
        : [...current, toolId],
    );
  };

  const startOver = async () => {
    const confirmed = window.confirm(
      "Se archivará esta conversación y Vibi dejará de usarla como contexto. ¿Empezar de cero?",
    );
    if (!confirmed) return;
    setResetError(null);
    try {
      const result = await reset.mutateAsync();
      setTransientItems([]);
      queryClient.setQueryData<ChatRuntimeState | null>(chatRuntimeKey, null);
      queryClient.setQueryData<ConversationState>(conversationKey, (current) =>
        mergeConversationState(current, result),
      );
    } catch (reason) {
      setResetError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo empezar una conversación nueva.",
      );
    }
  };

  return (
    <div className="chat-panel">
      <div className="chat-panel-bar">
        <span className="chat-engine"><Bot size={14} /> Claude Code · Haiku 4.5</span>
        <button
          type="button"
          className="chat-reset-button"
          onClick={() => void startOver()}
          disabled={history.isPending || send.isPending || reset.isPending}
        >
          <RotateCcw size={14} />
          {reset.isPending ? "Reiniciando…" : "Empezar de cero"}
        </button>
      </div>

      <div ref={conversationRef} className="conversation" aria-live="polite">
        {history.isError && (
          <p className="inline-error" role="alert">
            No se pudo cargar el historial. Puedes seguir escribiendo.
          </p>
        )}
        {resetError && <p className="inline-error" role="alert">{resetError}</p>}
        {history.isPending ? (
          <div className="chat-empty" aria-label="Cargando conversación">
            <span><Bot size={25} /></span>
            <p>Cargando conversación…</p>
          </div>
        ) : !items.length && (
          <div className="chat-empty">
            <span><Bot size={25} /></span>
            <h2>Pregunta, busca o actúa desde aquí</h2>
            <p>Claude Code conserva esta conversación y puede usar tus tools, archivos y terminal.</p>
          </div>
        )}
        {items.map((item) => (
          <div key={item.id} className={`log-row log-${item.kind}`}>
            <div className="log-gutter">
              <time className="log-time">{horaDe(item.at)}</time>
              <span className="log-mark" aria-hidden="true">{MARCAS[item.kind]}</span>
            </div>
            <div className="log-body">
              {item.kind === "files" ? (
                <ul className="log-files-list">
                  {item.files.map((file) => (
                    <li key={file.id}>
                      <File size={13} aria-hidden="true" />
                      <span className="log-file-name">{file.name}</span>
                      <span className="log-file-path">
                        {file.relative_path ?? "Archivo subido"}
                      </span>
                      <button
                        type="button"
                        className="log-file-get"
                        aria-label={`Descargar ${file.name}`}
                        onClick={() => void downloadFile(file)}
                      >
                        <Download size={14} />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : item.kind === "assistant" ? (
                <MarkdownContent>{item.text}</MarkdownContent>
              ) : (
                <p className="log-text">{item.text}</p>
              )}
            </div>
          </div>
        ))}
        {liveRuntime ? (
          <div className="log-row log-assistant log-live" aria-label={liveRuntime.label}>
            <div className="log-gutter">
              <span className="log-mark" aria-hidden="true">{MARCAS.assistant}</span>
            </div>
            <div className="log-body">
              {liveRuntime.text && <MarkdownContent>{liveRuntime.text}</MarkdownContent>}
              <p className="log-status">
                {liveRuntime.label}
                <i className="log-cursor" aria-hidden="true" />
              </p>
            </div>
          </div>
        ) : send.isPending && (
          <div className="log-row log-assistant log-live" aria-label="Vibi está escribiendo">
            <div className="log-gutter">
              <span className="log-mark" aria-hidden="true">{MARCAS.assistant}</span>
            </div>
            <div className="log-body">
              <p className="log-status">
                Pensando
                <i className="log-cursor" aria-hidden="true" />
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="chat-composer-wrap">
        <div className="chat-runtime-controls">
          <div className="chat-tool-picker">
            <button
              type="button"
              className={`chat-control-button${toolsOpen ? " is-active" : ""}`}
              aria-expanded={toolsOpen}
              aria-haspopup="listbox"
              onClick={() => setToolsOpen((current) => !current)}
              disabled={toolsQuery.isPending || send.isPending}
            >
              <Wrench size={15} />
              Tools
              {attachedToolIds.length > 0 && (
                <span className="chat-control-count">{attachedToolIds.length}</span>
              )}
            </button>
            {toolsOpen && (
              <div className="chat-tool-popover" role="listbox" aria-label="Adjuntar herramientas">
                <div className="chat-tool-popover-heading">
                  <div>
                    <strong>Herramientas para este mensaje</strong>
                    <small>Claude puede elegir las demás por contexto.</small>
                  </div>
                  <button type="button" onClick={() => setToolsOpen(false)} aria-label="Cerrar selector de herramientas">
                    <X size={15} />
                  </button>
                </div>
                <div className="chat-tool-options">
                  {availableTools.map((tool) => {
                    const selected = attachedToolIds.includes(tool.id);
                    return (
                      <button
                        key={tool.id}
                        type="button"
                        role="option"
                        aria-selected={selected}
                        className={selected ? "is-selected" : ""}
                        onClick={() => toggleTool(tool.id)}
                      >
                        <span className="chat-tool-check">{selected && <Check size={13} />}</span>
                        <span>
                          <strong>{tool.name}</strong>
                          <small>{tool.description}</small>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={thinkingEnabled}
            className={`thinking-toggle${thinkingEnabled ? " is-on" : ""}`}
            onClick={() => thinking.mutate(!thinkingEnabled)}
            disabled={history.isPending || thinking.isPending || send.isPending}
          >
            <Brain size={15} />
            <span>Thinking</span>
            <i aria-hidden="true"><b /></i>
          </button>
        </div>
        {attachedTools.length > 0 && (
          <div className="chat-attached-tools" aria-label="Herramientas adjuntas">
            {attachedTools.map((tool) => (
              <button type="button" key={tool.id} onClick={() => toggleTool(tool.id)}>
                <Wrench size={12} />
                {tool.name}
                <X size={12} />
              </button>
            ))}
          </div>
        )}
        {thinking.isError && (
          <p className="chat-control-error" role="alert">No se pudo cambiar Thinking.</p>
        )}
        <MessageComposer
          label="Mensaje"
          placeholder="Escribe un mensaje…"
          submitLabel="Enviar mensaje"
          pending={send.isPending || history.isPending || reset.isPending}
          onSubmit={submit}
        />
        <p>Enter envía · Mayús + Enter añade una línea · Las tools adjuntas se usan solo en este mensaje</p>
      </div>
    </div>
  );
}
