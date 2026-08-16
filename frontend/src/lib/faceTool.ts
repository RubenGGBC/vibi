import type { FaceToolState } from "./face3d";

/**
 * Qué cara pone Vibi según la herramienta que esté usando.
 *
 * Hasta ahora todas las herramientas ponían la misma cara (`working`), así que
 * un turno navegando media hora se veía igual que uno leyendo un archivo. Esto
 * es lo que las separa.
 *
 * La clasificación se hace **aquí y no en el servidor** porque los nombres los
 * pone cada motor y no hay lista cerrada: `agy` estrena tipos de paso sin
 * avisar (`CORTEX_STEP_TYPE_*`), Claude Code usa los suyos (`Bash`, `Glob`) y
 * los del MCP llegan con el servidor pegado delante
 * (`mcp__playwright__browser_click`). Un diccionario cerrado en el servidor
 * convertiría lo que no conoce en cadena vacía; así llega crudo y lo que no
 * encaje se queda en la cara genérica, que es una degradación honesta.
 */

/**
 * Se busca por trozos del nombre, en orden, y gana el primero que encaje: lo
 * específico va antes que lo general. `read` está al final justo por eso — es
 * subcadena de medio catálogo (`browser_read`, `spread`), y arriba se comería
 * las que sí sabemos clasificar mejor.
 */
const REGLAS: ReadonlyArray<readonly [string, FaceToolState, string]> = [
  // Internet
  ["search_web", "searching", "Buscando en internet"],
  ["web_search", "searching", "Buscando en internet"],
  ["websearch", "searching", "Buscando en internet"],
  ["webfetch", "browsing", "Consultando una página"],
  ["read_url", "browsing", "Consultando una página"],
  // El navegador de verdad, el que se ve abrirse
  ["browser_", "browsing", "Navegando"],
  ["playwright", "browsing", "Navegando"],
  // Tu pantalla
  ["screenshot", "peeking", "Mirando tu pantalla"],
  ["ui_snapshot", "peeking", "Mirando tu pantalla"],
  ["ui_batch", "peeking", "Manejando tu pantalla"],
  ["click", "peeking", "Manejando tu pantalla"],
  ["scroll", "peeking", "Manejando tu pantalla"],
  ["keyboard", "peeking", "Escribiendo en tu pantalla"],
  // El terminal
  ["terminal", "hacking", "En el terminal"],
  ["shell", "hacking", "En el terminal"],
  ["bash", "hacking", "En el terminal"],
  ["run_command", "hacking", "En el terminal"],
  ["execute", "hacking", "En el terminal"],
  // Archivos: buscar
  ["list_directory", "searching", "Mirando carpetas"],
  ["files_search", "searching", "Buscando archivos"],
  ["search_file", "searching", "Buscando archivos"],
  ["glob", "searching", "Buscando archivos"],
  ["grep", "searching", "Buscando en los archivos"],
  // Archivos: escribir
  ["create_note", "writing", "Tomando nota"],
  ["write", "writing", "Escribiendo"],
  ["edit", "writing", "Escribiendo"],
  ["replace", "writing", "Escribiendo"],
  // La malla y el resto del mundo
  ["send_file", "reaching", "Moviendo un archivo"],
  ["media", "vibing", "Poniendo música"],
  ["youtube", "vibing", "Poniendo música"],
  ["launch_app", "reaching", "Abriendo una aplicación"],
  ["open_url", "reaching", "Abriendo una dirección"],
  ["open_path", "reaching", "Abriendo algo en tu equipo"],
  ["devices", "reaching", "Hablando con tu equipo"],
  ["pc_", "reaching", "Trasteando en tu PC"],
  // Leer, al final: es subcadena de demasiadas cosas.
  ["read_file", "reading", "Leyendo"],
  ["view_file", "reading", "Leyendo"],
  ["read", "reading", "Leyendo"],
];

export interface CaraDeHerramienta {
  cara: FaceToolState;
  copy: string;
}

/** La genérica: no sabemos qué es, pero sabemos que está ocupada. */
const GENERICA: CaraDeHerramienta = { cara: "working", copy: "Trabajando en ello" };

/**
 * Clasifica el nombre crudo de una herramienta.
 *
 * Sin nombre devuelve la genérica en vez de nada: el turno **sí** está en una
 * herramienta —eso lo dice la fase, no esto—, y devolver nulo pondría cara de
 * pensar a algo que está trabajando.
 */
export function caraDeHerramienta(nombre: string | null | undefined): CaraDeHerramienta {
  const clave = (nombre ?? "").toLowerCase();
  if (!clave) return GENERICA;
  for (const [trozo, cara, copy] of REGLAS) {
    if (clave.includes(trozo)) return { cara, copy };
  }
  return GENERICA;
}
