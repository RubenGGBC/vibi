import type {
  ConversationMessage,
  ConversationState,
} from "../types";

export const conversationKey = [
  "conversation",
  "active",
  "messages",
] as const;

export const chatRuntimeKey = [
  "conversation",
  "active",
  "runtime",
] as const;

const mergeMessages = (
  current: ConversationMessage[],
  incoming: ConversationMessage[],
): ConversationMessage[] => {
  const byId = new Map(current.map((message) => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort(
    (left, right) =>
      left.created_at - right.created_at || left.id - right.id,
  );
};

export function mergeConversationState(
  current: ConversationState | undefined,
  incoming: ConversationState,
): ConversationState {
  if (!current) {
    return { ...incoming, conversation_changed: false };
  }
  if (current.conversation_id !== incoming.conversation_id) {
    // `conversation_changed` es una respuesta a una acción explícita —empezar
    // de cero, retomar una guardada—, así que manda sobre la fecha. Sin esto,
    // retomar una conversación vieja no hacía nada visible: su hilo es
    // anterior al que estaba abierto y la comparación de fechas lo descartaba.
    if (incoming.conversation_changed) {
      return { ...incoming, conversation_changed: false };
    }
    return current.conversation_created_at > incoming.conversation_created_at
      ? current
      : { ...incoming, conversation_changed: false };
  }
  if (incoming.conversation_changed) {
    return { ...incoming, conversation_changed: false };
  }
  return {
    conversation_id: current.conversation_id,
    conversation_created_at: current.conversation_created_at,
    conversation_changed: false,
    thinking_enabled: incoming.thinking_enabled,
    messages: mergeMessages(current.messages, incoming.messages),
  };
}

export function appendConversationMessage(
  current: ConversationState | undefined,
  message: ConversationMessage,
): ConversationState {
  return mergeConversationState(current, {
    conversation_id: message.conversation_id,
    conversation_created_at: message.created_at,
    conversation_changed: false,
    thinking_enabled: current?.thinking_enabled ?? false,
    messages: [message],
  });
}
