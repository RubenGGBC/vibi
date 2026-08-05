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

export type ActivityCategory =
  | "tareas"
  | "conversacion"
  | "archivos"
  | "proyectos"
  | "herramientas"
  | "cuenta"
  | "dispositivos";

export interface ActivitySummary {
  tareas_activas: number;
  esperando_aprobacion: number;
  tareas_completadas: number;
  almacenamiento_usado_bytes: number;
  almacenamiento_cuota_bytes: number;
  dispositivos_conocidos: number;
  dispositivos_recientes: number;
}

export interface ActivityItem {
  id: number;
  tipo: string;
  categoria: ActivityCategory;
  titulo: string;
  detalle: string;
  creado_en: number;
  enlace: string | null;
}

export interface ActivityResponse {
  resumen: ActivitySummary;
  eventos: ActivityItem[];
  siguiente_cursor: number | null;
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

export interface ToolSchemaProperty {
  title?: string;
  description?: string;
  type?: string | string[];
  enum?: Array<string | number | boolean | null>;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  anyOf?: ToolSchemaProperty[];
  oneOf?: ToolSchemaProperty[];
}

export interface ToolInputSchema {
  type?: string;
  title?: string;
  properties?: Record<string, ToolSchemaProperty>;
  required?: string[];
  additionalProperties?: boolean;
}

export interface ToolUsage {
  total: number;
  succeeded: number;
  failed: number;
  denied: number;
  success_rate: number | null;
  last_used_at: number | null;
  average_duration_ms: number | null;
}

export interface ToolInvocation {
  id: string;
  tool_id: string;
  status: "running" | "succeeded" | "failed" | "denied";
  error_code: string | null;
  requested_at: number;
  completed_at: number | null;
  duration_ms: number | null;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  scope: "system" | "personal" | "lab";
  primitive_id: string;
  permissions: string[];
  effects: string[];
  input_schema: ToolInputSchema;
  bound_arguments?: Record<string, unknown>;
  enabled: boolean;
  source: "builtin" | "human" | "agent";
  created_at: number | null;
  updated_at?: number | null;
  editable?: boolean;
  duplicable?: boolean;
  usage?: ToolUsage;
}

export interface SkillIssue {
  code: string;
  severity: "error" | "warning";
  message: string;
}

export interface SkillQuality {
  ready: boolean;
  score: number;
  issues: SkillIssue[];
}

export interface Skill {
  id: string;
  slug: string;
  name: string;
  description: string;
  instructions: string;
  examples: string[];
  tool_ids: string[];
  tools: Tool[];
  scope: "personal" | "lab";
  enabled: boolean;
  version: number;
  quality: SkillQuality;
  created_at: number;
  updated_at: number;
}

export interface SkillsResponse {
  skills: Skill[];
  summary: { active: number; drafts: number };
  available_tools: Tool[];
}

export interface SkillRun {
  response: string;
  skill_id: string;
  skill_version: number;
  tool_runs: Array<{
    tool_id: string;
    status: "succeeded";
    result: Record<string, unknown>;
  }>;
  artifacts: UserFile[];
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
  thinking_enabled: boolean;
  messages: ConversationMessage[];
}

export interface ChatRuntimeState {
  conversation_id: string;
  turn_id: string;
  label: string;
  text: string;
  /**
   * Cuántos bloques de texto ha cerrado el turno por pasar a una herramienta.
   *
   * Es un contador y no un booleano porque el estado se lee por suscripción:
   * quien locuta necesita distinguir «acaba de cerrar otro bloque» de «sigue
   * puesta la marca del anterior», y un turno puede encadenar herramientas.
   */
  boundaries: number;
}

export type MessageResponse =
  | { via: "rapida"; respuesta: string }
  | { via: "agentica"; task_id: string }
  | { via: "herramienta"; respuesta: string; artifacts: UserFile[] };

export type VoiceResponse =
  | { via: "rapida"; transcripcion: string; respuesta: string }
  | { via: "cerrar"; transcripcion: string; respuesta: "" }
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
      tipo: "chat_runtime";
      event: "started" | "progress";
      conversation_id: string;
      turn_id: string;
      label: string;
    }
  | {
      tipo: "chat_runtime";
      event: "delta";
      conversation_id: string;
      turn_id: string;
      delta: string;
      reset: boolean;
      /** El bloque de texto cerró aquí porque viene una herramienta detrás. */
      boundary?: boolean;
    }
  | {
      tipo: "chat_runtime";
      event: "finished";
      conversation_id: string;
      turn_id: string;
    }
  | {
      tipo: "conversation_reset";
      conversation_id: string;
      conversation_created_at: number;
      thinking_enabled: boolean;
    }
  | { tipo: "conexion_lista"; device_id: string }
  | { tipo: "archivo_actualizado"; archivo: UserFile }
  | { tipo: "archivo_eliminado"; archivo_id: string }
  | { tipo: "nodo_orden_aprobacion"; orden: NodeOrder }
  | { tipo: "nodo_orden_resuelta"; orden: NodeOrder }
  | { tipo: "pong" };

/** Una orden dirigida a otra máquina que espera (o esperaba) tu visto bueno. */
export type NodeOrder = {
  id: string;
  node_id: string;
  node_nombre?: string;
  capability: string;
  arguments: Record<string, unknown>;
  estado: string;
  aprobacion: "no_requiere" | "pendiente" | "aprobada" | "rechazada";
  riesgo: "bajo" | "medio" | "alto";
  motivo: string | null;
  created_at: number;
  expires_at: number;
};
