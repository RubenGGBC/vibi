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

type ChatItem =
  | { id: string; kind: "user" | "assistant"; text: string; clientRef?: string }
  | { id: string; kind: "files"; files: UserFile[] };

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
      { id: clientRef, kind: "user", text, clientRef },
    ]);
    if (history.data?.conversation_id) {
      const initialRuntime: ChatRuntimeState = {
        conversation_id: history.data.conversation_id,
        turn_id: clientRef,
        label: "Conectando con Claude Code…",
        text: "",
        boundaries: 0,
        fase: "arranque",
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
          { id: `${clientRef}-files`, kind: "files", files: result.artifacts },
        ]);
      }
    } catch (reason) {
      setTransientItems((current) => [
        ...current,
        {
          id: `${clientRef}-error`,
          kind: "assistant",
          text:
            reason instanceof ApiError
              ? reason.message
              : "No pude procesar el mensaje. Inténtalo de nuevo.",
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
        {items.map((item) => {
          if (item.kind === "files") {
            return (
              <div key={item.id} className="chat-file-results">
                {item.files.map((file) => (
                  <div key={file.id} className="chat-file-card">
                    <span><File size={18} /></span>
                    <div><strong>{file.name}</strong><small>{file.relative_path ?? "Archivo subido"}</small></div>
                    <button className="icon-button" aria-label={`Descargar ${file.name}`} onClick={() => void downloadFile(file)}><Download size={17} /></button>
                  </div>
                ))}
              </div>
            );
          }
          return (
            <div key={item.id} className={`bubble-row bubble-${item.kind}`}>
              {item.kind === "assistant" && <span className="bubble-avatar">✦</span>}
              <p>{item.text}</p>
            </div>
          );
        })}
        {liveRuntime ? (
          <div className="bubble-row bubble-assistant chat-live-row" aria-label={liveRuntime.label}>
            <span className="bubble-avatar">✦</span>
            <div className="chat-live-bubble">
              {liveRuntime.text && <p>{liveRuntime.text}</p>}
              <span className="chat-live-status">
                <i aria-hidden="true" />
                {liveRuntime.label}
              </span>
            </div>
          </div>
        ) : send.isPending && (
          <div className="bubble-row bubble-assistant" aria-label="Vibi está escribiendo">
            <span className="bubble-avatar">✦</span><span className="typing"><i /><i /><i /></span>
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
