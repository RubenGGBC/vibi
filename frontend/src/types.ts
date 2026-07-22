export type TaskState =
  | "pendiente"
  | "planificando"
  | "esperando_aprobacion"
  | "ejecutando"
  | "completada"
  | "rechazada"
  | "error";

export interface Task {
  id: string;
  user_id: string;
  prompt: string;
  estado: TaskState;
  plan: string | null;
  resultado: string | null;
  workspace: string | null;
  modelo: string;
  proyecto: string | null;
  creado_en: number;
  actualizado_en: number;
}

export interface User {
  id: string;
  nombre: string;
}

export interface ConversationMessage {
  id: number;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  origen: "pwa" | "telegram" | "cara";
  client_ref: string | null;
  tokens_aprox: number | null;
  created_at: number;
}

export interface ConversationState {
  conversation_id: string;
  conversation_created_at: number;
  conversation_changed: boolean;
  messages: ConversationMessage[];
}

export type MessageResponse =
  | { via: "rapida"; respuesta: string }
  | { via: "agentica"; task_id: string };

export type VoiceResponse =
  | { via: "rapida"; transcripcion: string; respuesta: string }
  | {
      via: "agentica";
      transcripcion: string;
      respuesta: string;
      task_id: string;
    };

export type ServerEvent =
  | { tipo: "tarea_actualizada"; task: Task }
  | { tipo: "notificacion"; texto: string; task_id?: string }
  | { tipo: "chat_message"; message: ConversationMessage }
  | {
      tipo: "conversation_reset";
      conversation_id: string;
      conversation_created_at: number;
    }
  | { tipo: "conexion_lista"; device_id: string }
  | { tipo: "pong" };
