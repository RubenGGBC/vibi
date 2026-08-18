/**
 * El vocabulario de caras de Vibi.
 *
 * Los cuatro primeros son el ciclo de voz y los usan las dos caras, la de la
 * PWA y la del companion. El resto cuenta lo que pasa en el turno.
 */

export type FaceVoiceState = "idle" | "listening" | "thinking" | "speaking";

/**
 * Las caras de trabajar, una por familia de herramienta.
 *
 * Se separan por **lo que hace**, no por el nombre de la herramienta: leer un
 * archivo del PC y leer uno del servidor son la misma cara porque para quien
 * mira son la misma cosa.
 *
 * Antes eran nueve y el catálogo de `faceTool` ya distinguía veinte frases
 * distintas, así que «Mirando tu pantalla» y «Manejando tu pantalla» acababan
 * con el mismo gesto. Catorce es lo que hace falta para que cada frase que ya
 * escribimos tenga cara propia; más sería inventarse diferencias que nadie ve.
 */
export type FaceToolState =
  | "working"
  | "searching"
  | "browsing"
  | "rummaging"
  | "reading"
  | "writing"
  | "noting"
  | "hacking"
  | "peeking"
  | "handling"
  | "launching"
  | "sending"
  | "reaching"
  | "vibing";

export type FaceState =
  | FaceVoiceState
  | FaceToolState
  /** El turno acaba de arrancar y el motor todavía está despertando. */
  | "arranque"
  | "waiting"
  | "alert"
  | "pleased"
  | "offline";

/**
 * `web` es la cara de la PWA, donde comparte página con el resto. `companion`
 * es la del escritorio, donde ocupa la ventana entera: ahí sigue al cursor y
 * se permite los tics de reposo.
 *
 * `web` es el valor por defecto a propósito: es el restringido, y quien monta
 * la cara sin decir nada —la PWA— es justo quien no debe seguir al cursor.
 */
export type FacePerfil = "web" | "companion";

/** Todos los estados, para recorrerlos sin olvidarse ninguno. */
export const ESTADOS: readonly FaceState[] = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "arranque",
  "working",
  "searching",
  "browsing",
  "rummaging",
  "reading",
  "writing",
  "noting",
  "hacking",
  "peeking",
  "handling",
  "launching",
  "sending",
  "reaching",
  "vibing",
  "waiting",
  "alert",
  "pleased",
  "offline",
];
