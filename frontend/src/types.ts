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
  /** El proyecto del que cuelga, o null si está suelto en tus archivos. */
  project_id: string | null;
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
  // "script" son las que Vibi se ha forjado: llevan código propio en vez de
  // una primitiva detrás, y por eso su primitive_id viene vacío.
  kind?: "primitive" | "script";
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
  version?: number;
  lineas?: number;
  peticion?: string;
  modelo?: string;
  comprobacion?: { estado: "ok" | "fallo" | "omitida"; error?: string };
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
  /** Los archivos que iban con el mensaje. Vacío en los que no llevaban. */
  adjuntos?: UserFile[];
}

/** Un proyecto: su carpeta de trabajo y lo que se ha guardado dentro. */
export interface Project {
  id: string;
  nombre: string;
  slug: string;
  descripcion: string;
  archivos: number;
  conversaciones: number;
  /**
   * Si su carpeta sigue existiendo en el workspace. Un proyecto sin carpeta
   * conserva sus archivos y conversaciones, pero no puede recibir encargos.
   */
  carpeta: boolean;
  created_at: number;
  updated_at: number;
}

export interface ProjectsResponse {
  proyectos: string[];
  detalles: Project[];
}

/** Una conversación con nombre, que se puede volver a abrir. */
export interface SavedConversation {
  id: string;
  titulo: string | null;
  estado: "activa" | "archivada";
  project_id: string | null;
  mensajes: number;
  created_at: number;
  updated_at: number;
}

export interface ConversationState {
  conversation_id: string;
  conversation_created_at: number;
  conversation_changed: boolean;
  thinking_enabled: boolean;
  messages: ConversationMessage[];
  /** Solo al retomar una guardada: cómo se llama y de qué proyecto viene. */
  titulo?: string | null;
  project_id?: string | null;
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
  /**
   * En qué anda el turno ahora mismo.
   *
   * Sale del tipo de evento y no del texto de `label`, que son frases en
   * español pensadas para leerse («Ejecutando en el terminal…») y cambian sin
   * avisar. La cara del companion lo usa para distinguir estar pensando de
   * estar trabajando, que hasta ahora eran la misma expresión.
   */
  fase: "arranque" | "herramienta" | "redactando";
  /**
   * Cuál se está usando, para poner una cara distinta a cada familia.
   *
   * Se conserva mientras dure la fase de herramienta y se limpia al pasar a
   * redactar: si no, Vibi seguiría con cara de estar navegando mientras te
   * cuenta lo que ha encontrado.
   */
  herramienta: string;
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
  // `hablar` lo ponen solo las notificaciones del sistema: por este canal
  // también llegan avisos que se leen y no se dicen, como una tarea terminada.
  | { tipo: "notificacion"; texto: string; task_id?: string; hablar?: boolean }
  | { tipo: "chat_message"; message: ConversationMessage }
  | {
      tipo: "chat_runtime";
      event: "started" | "progress";
      conversation_id: string;
      turn_id: string;
      label: string;
      /**
       * El nombre crudo de la herramienta en marcha, tal como lo llama su
       * motor: `Bash`, `SEARCH_WEB`, `mcp__playwright__browser_click`. De él
       * cuelga la cara, y va aparte de `label` porque ese es texto en español
       * que se reescribe cuando suena mejor de otra forma. Vacío en `started` y
       * en los pasos que no son de herramienta.
       */
      herramienta?: string;
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
  // Estos dos los emitía el servidor desde hace tiempo sin que nadie los
  // declarase aquí: ninguna pantalla los usaba, así que pasaban por el canal y
  // se descartaban en silencio. La cara del companion sí los quiere.
  | { tipo: "transferencia"; transferencia: Transferencia }
  | { tipo: "nodo_presencia"; nodo: { id: string; nombre?: string; online?: boolean } }
  | { tipo: "vigilancia"; activa: boolean; que_espero: string }
  | { tipo: "pong" };

/** Un archivo viajando de un dispositivo tuyo a otro. */
export interface Transferencia {
  id: string;
  nombre: string;
  estado: string;
  origen_node_id: string | null;
  destino_node_id: string | null;
  destino_canal: string | null;
  file_id: string | null;
  bytes_esperados: number | null;
  bytes_recibidos: number | null;
  error: string | null;
  created_at: number;
}

/** Una máquina de tu malla, tal como la serializa `nodes.serialize`. */
export interface NodeDevice {
  id: string;
  nombre: string;
  plataforma: string;
  estado: string;
  /** Lo que ese nodo sabe hacer. Un servidor sin escritorio no trae las de interfaz. */
  capacidades: string[];
  shell_habilitado: boolean;
  conectado: boolean;
  last_seen: number;
  created_at: number;
}

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

/* Especialización por usuario */

export type ClaseAfirmacion =
  | "dominio"
  | "rasgo"
  | "herramienta"
  | "preferencia"
  | "aficion";
export type ProcedenciaAfirmacion = "entrevista" | "inventario" | "uso";

export interface Afirmacion {
  id: number;
  user_id: string;
  clase: ClaseAfirmacion;
  valor: string;
  procedencia: ProcedenciaAfirmacion;
  confianza: number;
  apoyos: number;
  contras: number;
  creada_en: number;
  movida_en: number;
}

export type TipoCapacidad = "mcp" | "skill" | "vigilancia";
export type NivelCapacidad = "completo" | "catalogo" | "propuesta_retirada";

export interface Capacidad {
  id: number;
  user_id: string;
  tipo: TipoCapacidad;
  referencia: string;
  justificacion: string;
  transporte: string;
  nivel: NivelCapacidad;
  aprobada_en: number | null;
  usos: number;
  ultimo_uso: number | null;
  endpoint?: string;
}

export interface PerfilMetricas {
  tasa_de_aceptacion: number;
  supervivencia_14dias: number;
  total_afirmaciones: number;
  total_capacidades: number;
}

export interface PerfilUsuario {
  user_id: string;
  resumen: string;
  afirmaciones: Afirmacion[];
  capacidades: Capacidad[];
  metricas: PerfilMetricas;
}

export interface Hipotesis {
  clase: string;
  valor: string;
  evidencia: string;
}

export interface Propuesta {
  tipo: string;
  referencia: string;
  titulo: string;
  justificacion: string;
  transporte: string;
  bloque: "pedido" | "encaja";
  endpoint: string;
  /** Cómo se lanza uno local: «npm:paquete@version». Vacío si es remoto. */
  paquete: string;
}

/**
 * Algo que la entrevista no pudo aplicar y por qué.
 *
 * Casi siempre es una propuesta nuestra que llegó incompleta —un MCP remoto
 * sin endpoint—, no algo que el usuario hiciera mal. Se aparta para no tumbar
 * el resto, pero se cuenta: había marcado ese servidor y si no, lo vería
 * desaparecer sin explicación.
 */
export interface DescarteEntrevista {
  que: "afirmacion" | "capacidad";
  referencia: string;
  motivo: string;
}

/** Un turno de la entrevista hablada: quién habló y qué dijo. */
export interface TurnoHistorial {
  rol: "vibi" | "usuario";
  texto: string;
}

export interface ResumenEntrevista {
  afirmaciones: Array<{ clase: ClaseAfirmacion; valor: string }>;
  texto_libre: string;
}

export interface TurnoEntrevista {
  vibi_dice: string;
  terminado: boolean;
  resumen?: ResumenEntrevista;
}
