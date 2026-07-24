import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import type { ServerEvent, Task } from "../types";
import type { ConversationState } from "../types";
import { clearToken, getToken } from "./auth";
import { apiFetch } from "./api";
import {
  appendConversationMessage,
  conversationKey,
  mergeConversationState,
} from "./conversation";
import { getDeviceIdentity } from "./device";
import { taskKeys, upsertTask } from "./tasks";

export function applyServerEvent(client: QueryClient, event: ServerEvent): void {
  if (event.tipo === "tarea_actualizada") {
    const queries = client.getQueryCache().findAll({ queryKey: taskKeys.all });
    for (const query of queries) {
      const filters = query.queryKey[1] as
        | { estado?: string; proyecto?: string }
        | undefined;
      const matches =
        (!filters?.estado || event.task.estado === filters.estado) &&
        (!filters?.proyecto ||
          event.task.proyecto?.toLocaleLowerCase() ===
            filters.proyecto.toLocaleLowerCase());
      client.setQueryData<Task[]>(query.queryKey, (current) => {
        if (!current) return current;
        if (matches) return upsertTask(current, event.task);
        return current.filter(({ id }) => id !== event.task.id);
      });
    }
    client.setQueryData(taskKeys.detail(event.task.id), event.task);
    return;
  }
  if (event.tipo === "chat_message") {
    client.setQueryData<ConversationState>(conversationKey, (current) =>
      appendConversationMessage(current, event.message),
    );
    return;
  }
  if (event.tipo === "conversation_reset") {
    client.setQueryData<ConversationState>(conversationKey, {
      conversation_id: event.conversation_id,
      conversation_created_at: event.conversation_created_at,
      conversation_changed: false,
      messages: [],
    });
    return;
  }
  if (
    event.tipo === "archivo_actualizado" ||
    event.tipo === "archivo_eliminado"
  ) {
    void client.invalidateQueries({ queryKey: ["files"] });
  }
}

async function catchUpConversation(client: QueryClient): Promise<void> {
  const current = client.getQueryData<ConversationState>(conversationKey);
  let afterId = current?.messages.at(-1)?.id;
  let shouldContinue = true;
  while (shouldContinue) {
    const cursor = afterId ? `&after_id=${afterId}` : "";
    const incoming = await apiFetch<ConversationState>(
      `/api/conversations/active/messages?limit=50${cursor}`,
    );
    client.setQueryData<ConversationState>(conversationKey, (cached) =>
      mergeConversationState(cached, incoming),
    );
    if (
      !afterId ||
      incoming.conversation_changed ||
      incoming.messages.length < 50
    ) {
      shouldContinue = false;
      continue;
    }
    const nextAfterId = incoming.messages.at(-1)?.id;
    if (!nextAfterId || nextAfterId === afterId) {
      shouldContinue = false;
    } else {
      afterId = nextAfterId;
    }
  }
}

export function useEvents(): void {
  const client = useQueryClient();

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;
    let stopped = false;
    let attempts = 0;
    let heartbeat: number | undefined;
    const identity = getDeviceIdentity();

    const stopHeartbeat = () => {
      if (heartbeat) window.clearInterval(heartbeat);
      heartbeat = undefined;
    };

    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${window.location.host}/api/eventos`;
      socket = new WebSocket(url);
      socket.onopen = () => {
        socket?.send(JSON.stringify({ token, ...identity }));
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as ServerEvent;
          applyServerEvent(client, event);
          if (event.tipo === "conexion_lista") {
            attempts = 0;
            stopHeartbeat();
            heartbeat = window.setInterval(() => {
              if (socket?.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ tipo: "ping" }));
              }
            }, 30_000);
            void catchUpConversation(client).catch(() => {
              void client.invalidateQueries({ queryKey: conversationKey });
            });
          }
        } catch {
          // Un evento desconocido no debe romper el canal vivo.
        }
      };
      socket.onclose = (event) => {
        stopHeartbeat();
        if (stopped) return;
        if (event.code === 4401) {
          clearToken();
          window.dispatchEvent(new CustomEvent("morgana:unauthorized"));
          window.history.replaceState({}, "", "/login");
          window.dispatchEvent(new PopStateEvent("popstate"));
          return;
        }
        attempts += 1;
        reconnectTimer = window.setTimeout(
          connect,
          Math.min(1_000 * 2 ** attempts, 20_000),
        );
      };
    };

    connect();
    return () => {
      stopped = true;
      stopHeartbeat();
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [client]);
}
