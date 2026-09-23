import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Bot, Download, File, Paperclip, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { useConfirm } from "../components/ConfirmDialog";
import { MessageComposer } from "../components/MessageComposer";
import { useAdjuntos } from "../lib/adjuntos";
import { ApiError, apiBlob, apiFetch } from "../lib/api";
import {
  conversationKey,
  mergeConversationState,
} from "../lib/conversation";
import type {
  ConversationState,
  MessageResponse,
  UserFile,
} from "../types";

type ChatItem =
  | {
      id: string;
      kind: "user" | "assistant";
      text: string;
      clientRef?: string;
      adjuntos?: UserFile[];
    }
  | { id: string; kind: "task"; taskId: string }
  | { id: string; kind: "files"; files: UserFile[] };

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

export function ChatPage() {
  const queryClient = useQueryClient();
  const { confirm, dialog } = useConfirm();
  const [transientItems, setTransientItems] = useState<ChatItem[]>([]);
  const [resetError, setResetError] = useState<string | null>(null);
  const conversationId = useRef<string | null>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const adjuntos = useAdjuntos();
  const history = useQuery<ConversationState>({
    queryKey: conversationKey,
    queryFn: () =>
      apiFetch<ConversationState>(
        "/api/conversations/active/messages?limit=50",
    ),
    structuralSharing: (current, incoming) =>
      mergeConversationState(
        current as ConversationState | undefined,
        incoming as ConversationState,
      ),
  });
  const send = useMutation({
    mutationFn: ({
      texto,
      clientRef,
      fileIds,
    }: {
      texto: string;
      clientRef: string;
      fileIds: string[];
    }) =>
      apiFetch<MessageResponse>("/api/mensaje", {
        method: "POST",
        body: JSON.stringify({
          texto,
          client_ref: clientRef,
          file_ids: fileIds,
        }),
      }),
  });
  const reset = useMutation({
    mutationFn: () =>
      apiFetch<ConversationState>(
        "/api/conversations/reset",
        { method: "POST" },
      ),
  });

  useEffect(() => {
    const nextId = history.data?.conversation_id;
    if (!nextId) return;
    if (conversationId.current && conversationId.current !== nextId) {
      setTransientItems([]);
    }
    conversationId.current = nextId;
  }, [history.data?.conversation_id]);

  const messages = history.data?.messages ?? [];
  const reconciledRefs = new Set(
    messages.flatMap((message) =>
      message.client_ref ? [message.client_ref] : [],
    ),
  );
  const serverItems: ChatItem[] = messages.map((message) => ({
    id: `message-${message.id}`,
    kind: message.role,
    text: message.content,
    adjuntos: message.adjuntos ?? [],
  }));
  const visibleTransientItems = transientItems.filter(
    (item) =>
      !("clientRef" in item) ||
      !item.clientRef ||
      !reconciledRefs.has(item.clientRef),
  );
  const items = [...serverItems, ...visibleTransientItems];

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const conversation = conversationRef.current;
      if (conversation) conversation.scrollTop = conversation.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [items, send.isPending]);

  const submit = async (text: string) => {
    const clientRef = crypto.randomUUID();
    const adjuntados = [...adjuntos.archivos];
    setTransientItems((current) => [
      ...current,
      { id: clientRef, kind: "user", text, clientRef, adjuntos: adjuntados },
    ]);
    try {
      const result = await send.mutateAsync({
        texto: text,
        clientRef,
        fileIds: adjuntados.map((archivo) => archivo.id),
      });
      adjuntos.limpiar();
      if (result.via === "rapida" || result.via === "herramienta") {
        await history.refetch();
        if (result.via === "herramienta" && result.artifacts.length) {
          setTransientItems((current) => [
            ...current,
            {
              id: `${clientRef}-files`,
              kind: "files",
              files: result.artifacts,
            },
          ]);
        }
      } else {
        setTransientItems((current) => [
          ...current,
          {
            id: `${clientRef}-task`,
            kind: "task",
            taskId: result.task_id,
          },
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
    }
  };

  const startOver = async () => {
    const confirmed = await confirm(
      "Se archivará esta conversación y Vibi dejará de usarla como contexto. ¿Empezar de cero?",
    );
    if (!confirmed) return;
    setResetError(null);
    try {
      const result = await reset.mutateAsync();
      setTransientItems([]);
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
    <section className="chat-page">
      <header className="chat-header">
        <div>
          <p className="eyebrow">Vía rápida</p>
          <h1>Habla con Vibi</h1>
        </div>
        <div className="chat-actions">
          <span className="chat-engine"><Sparkles size={14} /> Groq</span>
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
      </header>

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
            <h2>Pregunta, resume o piensa en voz alta</h2>
            <p>Si el mensaje requiere trabajar sobre código, lo convertiré en una tarea con plan.</p>
          </div>
        )}
        {items.map((item) => {
          if (item.kind === "task") {
            return (
              <div key={item.id} className="agentic-card">
                <span className="agentic-mark">✦</span>
                <div><strong>Tarea encolada</strong><p>Prepararé un plan antes de tocar el proyecto.</p></div>
                <Link to={`/tareas/${item.taskId}`} aria-label="Abrir tarea encolada"><ArrowUpRight size={18} /></Link>
              </div>
            );
          }
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
              <div className="bubble-content">
                <p>{item.text}</p>
                {item.adjuntos && item.adjuntos.length > 0 && (
                  <ul className="bubble-adjuntos" aria-label="Archivos adjuntos del mensaje">
                    {item.adjuntos.map((archivo) => (
                      <li key={archivo.id}>
                        <Paperclip size={12} aria-hidden />
                        <span>{archivo.name}</span>
                        <button
                          type="button"
                          aria-label={`Descargar ${archivo.name}`}
                          onClick={() => void downloadFile(archivo)}
                        >
                          <Download size={13} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          );
        })}
        {send.isPending && (
          <div className="bubble-row bubble-assistant" aria-label="Vibi está escribiendo">
            <span className="bubble-avatar">✦</span><span className="typing"><i /><i /><i /></span>
          </div>
        )}
      </div>

      <div className="chat-composer-wrap">
        <MessageComposer
          label="Mensaje"
          placeholder="Escribe un mensaje…"
          submitLabel="Enviar mensaje"
          pending={send.isPending || history.isPending || reset.isPending}
          onSubmit={submit}
          adjuntos={adjuntos.archivos}
          onAdjuntar={(archivos) => void adjuntos.añadir(archivos)}
          onQuitarAdjunto={adjuntos.quitar}
          subiendoAdjunto={adjuntos.subiendo}
          errorAdjunto={adjuntos.error}
        />
        <p>Enter envía · Mayús + Enter añade una línea · El clip adjunta archivos al mensaje</p>
      </div>
      {dialog}
    </section>
  );
}
