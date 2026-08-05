import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";

/**
 * Avisos del sistema para lo que no puede esperar a que mires la ventana.
 *
 * Nunca lanza: quedarse sin notificación es un incordio, pero tumbar el turno
 * de voz por ello sería mucho peor. Si el permiso está denegado, calla.
 */
export async function notificar(
  titulo: string,
  cuerpo: string,
): Promise<void> {
  try {
    let permitido = await isPermissionGranted();
    if (!permitido) {
      permitido = (await requestPermission()) === "granted";
    }
    if (!permitido) return;
    sendNotification({ title: titulo, body: cuerpo });
  } catch {
    // Fuera de Tauri (o sin el plugin) no hay a quién avisar.
  }
}
