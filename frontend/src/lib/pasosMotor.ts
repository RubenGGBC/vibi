/**
 * Cómo se leen los pasos del motor en la ventana de proceso.
 *
 * Lo que llega del servidor son los nombres que usa `agy` por dentro
 * (`CORTEX_STEP_TYPE_RUN_COMMAND`), y eso no se le enseña a nadie. La
 * traducción vive aquí, en el frontend, por el mismo motivo que el catálogo de
 * caras: el servidor manda la clave cruda porque no hay lista cerrada —`agy`
 * estrena tipos sin avisar— y quien no la conozca tiene que poder apañárselas.
 */

export type PasoMotor = {
  turno: string;
  tipo: string;
  estado: string;
  detalle: string;
  momento: number;
};

/** Los que salen a todas horas, dichos como los diría una persona. */
const NOMBRES: Record<string, string> = {
  RUN_COMMAND: "Terminal",
  SEARCH_WEB: "Buscando",
  VIEW_FILE: "Leyendo",
  LIST_DIRECTORY: "Mirando carpeta",
  LIST_DIR: "Mirando carpeta",
  EDIT_FILE: "Editando",
  WRITE_FILE: "Escribiendo",
  GREP_SEARCH: "Buscando en archivos",
  CALL_MCP_TOOL: "Herramienta",
  BROWSER_NAVIGATE: "Navegando",
  CAPTURE_BROWSER_SCREENSHOT: "Mirando la pantalla",
  COMMAND_STATUS: "Esperando al comando",
};

export function nombreLegible(tipo: string): string {
  if (!tipo) return "Paso";
  const desnudo = tipo.replace(/^CORTEX_STEP_TYPE_/, "");
  const conocido = NOMBRES[desnudo];
  if (conocido) return conocido;
  // Lo desconocido, al menos legible: `BATTLE_MODE` -> `Battle mode`.
  const palabras = desnudo.toLowerCase().replace(/_/g, " ").trim();
  return palabras ? palabras[0].toUpperCase() + palabras.slice(1) : "Paso";
}

/** El detalle listo para una línea: sin saltos y con la forma que le toque. */
export function resumirPaso(paso: PasoMotor): string {
  const plano = paso.detalle.replace(/\s+/g, " ").trim();
  if (!plano) return "";
  // Una búsqueda es una frase, no un comando: entrecomillarla evita que se lea
  // como algo que se ha ejecutado.
  if (paso.tipo.includes("SEARCH_WEB")) return `«${plano}»`;
  return plano;
}
