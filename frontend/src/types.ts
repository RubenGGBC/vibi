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

export interface UserFile {
  id: string;
  name: string;
  source: "managed" | "workspace";
  relative_path: string | null;
  media_type: string | null;
  size_bytes: number;
  modified_at: number;
  created_at: number;
  download_url: string;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  scope: "system" | "personal" | "lab";
  primitive_id: string;
  permissions: string[];
  effects: string[];
  input_schema: Record<string, unknown>;
  bound_arguments?: Record<string, unknown>;
  enabled: boolean;
  source: "builtin" | "human" | "agent";
  created_at: number | null;
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
  | { via: "agentica"; task_id: string }
  | { via: "herramienta"; respuesta: string; artifacts: UserFile[] };

export type VoiceResponse =
  | { via: "rapida"; transcripcion: string; respuesta: string }
  | {
      via: "herramienta";
      transcripcion: string;
      respuesta: string;
      artifacts: UserFile[];
    }
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
  | { tipo: "archivo_actualizado"; archivo: UserFile }
  | { tipo: "archivo_eliminado"; archivo_id: string }
  | { tipo: "pong" };
