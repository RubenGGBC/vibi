export type DeviceType = "movil" | "pc" | "kiosko";

export interface DeviceIdentity {
  device_id: string;
  device_type: DeviceType;
  device_name: string;
}

const DEVICE_ID_KEY = "morgana:device-id";
const FACE_DEVICE_ID_KEY = "morgana:face-device-id";

const browserName = (userAgent: string): string => {
  if (/Edg\//i.test(userAgent)) return "Edge";
  if (/Firefox\//i.test(userAgent)) return "Firefox";
  if (/Chrome\//i.test(userAgent)) return "Chrome";
  if (/Safari\//i.test(userAgent)) return "Safari";
  return "Navegador";
};

export function getDeviceIdentity(): DeviceIdentity {
  const kiosk = window.location.pathname.startsWith("/cara");
  const mobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  const storageKey = kiosk ? FACE_DEVICE_ID_KEY : DEVICE_ID_KEY;
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(storageKey);
  } catch {
    // Algunos modos privados bloquean localStorage; la sesión seguirá funcionando.
  }

  const generated = crypto.randomUUID();
  const deviceId = stored ?? (kiosk ? `cara:${generated}` : generated);
  if (!stored) {
    try {
      window.localStorage.setItem(storageKey, deviceId);
    } catch {
      // La identidad será efímera si el navegador no permite persistirla.
    }
  }

  const deviceType: DeviceType = kiosk ? "kiosko" : mobile ? "movil" : "pc";
  const formFactor = kiosk ? "kiosco" : mobile ? "móvil" : "PC";
  return {
    device_id: deviceId,
    device_type: deviceType,
    device_name: `${browserName(navigator.userAgent)} en ${formFactor}`,
  };
}
