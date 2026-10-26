import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";

/**
 * Avisos del sistema para lo que no puede esperar a que mires la ventana.
 *
 * Hay **dos** sitios donde vive Vibi y cada uno tiene su forma de sacar un
 * toast: el companion es una app de escritorio y va por el plugin de Tauri; la
 * PWA es una pestaña del navegador y va por la API del navegador. Antes solo
 * existía el primer camino, así que en Edge o Firefox no salía nada de nada
 * —el `catch` se lo tragaba— y el aviso solo se veía abriendo el hilo.
 *
 * Nunca lanza: quedarse sin notificación es un incordio, pero tumbar el turno
 * de voz por ello sería mucho peor. Si el permiso está denegado, calla.
 */
export async function notificar(
  titulo: string,
  cuerpo: string,
): Promise<void> {
  if (await porTauri(titulo, cuerpo)) return;
  await porNavegador(titulo, cuerpo);
}

/**
 * El toast de «Vibi ha mirado tus notificaciones», con lo que decidió dentro.
 *
 * Vive aquí y no en quien lo llama porque lo llaman **dos** sitios y el texto
 * tiene que ser el mismo: la cara flotante cuando esto es la aplicación de
 * escritorio, y el hilo de chat cuando es una pestaña. Quién de los dos habla
 * lo decide el que llama —ver `corriendoEnLaApp`—, porque si hablaran los dos
 * saldrían dos globos de lo mismo.
 *
 * Si está esperando respuesta, la pregunta gana al resumen: es lo único del
 * globo sobre lo que puedes hacer algo.
 */
export async function notificarAvisosDeliberados(evento: {
  apps?: string;
  dicho?: string;
  pregunta?: string;
}): Promise<void> {
  await notificar(
    evento.apps ? `Vibi · ${evento.apps}` : "Vibi ha mirado tus notificaciones",
    evento.pregunta || evento.dicho || "Te ha dejado escrito lo que decidió.",
  );
}

/** Devuelve si esto es el companion, que es quien sabe usar este camino. */
async function porTauri(titulo: string, cuerpo: string): Promise<boolean> {
  try {
    let permitido = await isPermissionGranted();
    if (!permitido) {
      permitido = (await requestPermission()) === "granted";
    }
    // Aunque haya dicho que no, esto **sí** era Tauri: se devuelve `true` para
    // no intentarlo otra vez por el navegador y acabar avisando dos veces.
    if (permitido) sendNotification({ title: titulo, body: cuerpo });
    return true;
  } catch {
    return false;
  }
}

async function porNavegador(titulo: string, cuerpo: string): Promise<void> {
  if (typeof Notification === "undefined") return;
  try {
    const permiso =
      Notification.permission === "default"
        ? await Notification.requestPermission()
        : Notification.permission;
    if (permiso !== "granted") return;

    // Por el service worker cuando lo hay. Es lo que hace que el toast quede
    // en el centro de notificaciones en vez de desvanecerse con la pestaña, y
    // en algunos navegadores `new Notification()` ni siquiera está permitido
    // si hay uno registrado.
    //
    // Su propio try: buscarlo puede fallar por su cuenta, y perder el aviso
    // porque la *consulta* del service worker reventó sería absurdo. Lo pilló
    // una prueba sin `navigator`.
    let registro: ServiceWorkerRegistration | undefined;
    try {
      registro =
        typeof navigator === "undefined"
          ? undefined
          : await navigator.serviceWorker?.getRegistration();
    } catch {
      registro = undefined;
    }
    if (registro) {
      await registro.showNotification(titulo, { body: cuerpo });
      return;
    }
    new Notification(titulo, { body: cuerpo });
  } catch {
    // Sin permiso, sin soporte, o el navegador lo bloqueó: no hay a quién
    // avisar y no es motivo para romper nada.
  }
}
