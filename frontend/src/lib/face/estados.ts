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
  | "vibing"
  /**
   * Escribiéndose una herramienta nueva en la forja.
   *
   * Tiene cara propia porque es la única que tarda un minuto sin enseñar nada
   * por el camino: no hay archivo que se escriba ni página que se abra, solo
   * otro modelo pensando. Sin un gesto que lo cuente, forjar y colgarse se ven
   * exactamente igual.
   */
  | "forjando"
  /**
   * Trabajando en la trastienda, el escritorio que no ves.
   *
   * Es una familia de herramienta y no un estado aparte porque lo que la
   * dispara es una herramienta —`devices.trastienda`—, igual que las demás. Lo
   * que la separa del resto no es qué hace sino **dónde**: se recoge en su
   * huevo y trabaja donde no la tapas ni te tapa.
   */
  | "trastienda";

export type FaceState =
  | FaceVoiceState
  | FaceToolState
  /** El turno acaba de arrancar y el motor todavía está despertando. */
  | "arranque"
  /** En stand-by: mirando algo por encargo y callada hasta que pase. */
  | "vigilando"
  | "waiting"
  /**
   * Pide permiso, pero para algo que da miedo.
   *
   * Se separa de `waiting` porque el servidor **sí** sabe cuál es el comando:
   * poner la misma cara a `ls` que a `rm -rf` desperdicia lo único que
   * distingue una decisión de un trámite.
   */
  | "recelo"
  /** Le has dicho que no. Dura poco y vuelve a lo suyo. */
  | "denegada"
  | "alert"
  /** Ha fallado algo y necesita que lo mires. Más fuerte que `alert`. */
  | "fallo"
  /** El canal se ha caído con un turno vivo. No es lo mismo que dormirse. */
  | "perdida"
  | "pleased"
  /** Un encargo largo que acaba bien. `pleased` se queda para el acuse corto. */
  | "logro"
  /** Primer arranque en un equipo nuevo, mientras se vincula. */
  | "vinculando"
  /** La ventana está cambiando de talla. Es una transición, no un gesto. */
  | "cambiando"
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
  "vigilando",
  "trastienda",
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
  "forjando",
  "waiting",
  "recelo",
  "denegada",
  "alert",
  "fallo",
  "perdida",
  "pleased",
  "logro",
  "vinculando",
  "cambiando",
  "offline",
];
