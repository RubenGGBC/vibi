/**
 * Dónde cree la interfaz que está viviendo.
 *
 * La misma interfaz corre en dos sitios muy distintos: servida por el core en
 * un navegador, y dentro de la ventana de escritorio. La diferencia no es
 * cosmética — cambia a dónde van las peticiones y cómo se navega entre
 * pantallas—, y no distinguirlo dejaba la ventana de la aplicación en negro,
 * cargada pero incapaz de hablar con nada.
 */

/** El puerto donde escucha el core en la máquina del usuario. */
export const CORE_LOCAL = "http://127.0.0.1:8000";

/**
 * Si esto es la aplicación de escritorio y no una pestaña.
 *
 * Se comprueban dos cosas porque cada una llega en un momento distinto: el
 * protocolo está desde el primer instante, mientras que el puente que Tauri
 * inyecta puede no estar todavía cuando este módulo se evalúa. Con solo el
 * puente, un arranque rápido se tomaría por navegador.
 */
export const corriendoEnLaApp = (): boolean => {
  if (typeof window === "undefined") return false;
  if ("__TAURI_INTERNALS__" in window) return true;
  const protocolo = window.location?.protocol ?? "";
  return protocolo === "tauri:" || window.location?.hostname === "tauri.localhost";
};

/**
 * La base a la que dirigir las peticiones.
 *
 * Vacía en el navegador a propósito: ahí la interfaz la sirve el propio core,
 * así que una ruta relativa ya cae donde debe y funciona igual da por qué
 * dirección hayas entrado —localhost, la IP de la tailnet o un dominio—.
 * Fijarla rompería justo eso.
 */
export const baseDeLaApi = (): string => (corriendoEnLaApp() ? CORE_LOCAL : "");
