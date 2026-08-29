import type { FaceState } from "../estados";

/** Las ocho familias visuales aprobadas para la primera fase del companion. */
export type CompanionFamily =
  | "reposo"
  | "recelo"
  | "contenta"
  | "trabajando"
  | "duda"
  | "hablando"
  | "ejecutando"
  | "buscando";

export type CompanionAccessory =
  | "none"
  | "question"
  | "wave"
  | "terminal"
  | "magnifier";

export type CompanionEye =
  | "pill"
  | "suspicious-left"
  | "suspicious-right"
  | "happy"
  | "soft"
  | "round"
  | "dash"
  | "chevron";

export interface CompanionPose {
  leftEye: CompanionEye;
  rightEye: CompanionEye;
  accessory: CompanionAccessory;
  mouth: boolean;
  baseTilt: number;
}

/** El cuerpo es siempre el mismo: una pose solo cambia expresión y porte. */
export const POSES: Record<CompanionFamily, CompanionPose> = {
  reposo: {
    leftEye: "pill",
    rightEye: "pill",
    accessory: "none",
    mouth: false,
    baseTilt: -4,
  },
  recelo: {
    leftEye: "suspicious-left",
    rightEye: "suspicious-right",
    accessory: "none",
    mouth: false,
    baseTilt: -7,
  },
  contenta: {
    leftEye: "happy",
    rightEye: "happy",
    accessory: "none",
    mouth: false,
    baseTilt: -4,
  },
  trabajando: {
    leftEye: "soft",
    rightEye: "soft",
    accessory: "none",
    mouth: true,
    baseTilt: -3,
  },
  duda: {
    leftEye: "round",
    rightEye: "round",
    accessory: "question",
    mouth: false,
    baseTilt: 3,
  },
  hablando: {
    leftEye: "soft",
    rightEye: "soft",
    accessory: "wave",
    mouth: false,
    baseTilt: -2,
  },
  ejecutando: {
    leftEye: "dash",
    rightEye: "chevron",
    accessory: "terminal",
    mouth: false,
    baseTilt: -5,
  },
  buscando: {
    leftEye: "pill",
    rightEye: "pill",
    accessory: "magnifier",
    mouth: false,
    baseTilt: -4,
  },
};

/**
 * Correspondencia temporal: ningún estado funcional queda mudo mientras se
 * diseñan las caras posteriores a estas ocho.
 */
export const FAMILY_BY_STATE: Record<FaceState, CompanionFamily> = {
  idle: "reposo",
  vigilando: "reposo",
  cambiando: "reposo",
  offline: "reposo",

  recelo: "recelo",
  denegada: "recelo",
  alert: "recelo",
  fallo: "recelo",
  perdida: "recelo",

  pleased: "contenta",
  logro: "contenta",
  vibing: "contenta",

  working: "trabajando",
  reading: "trabajando",
  writing: "trabajando",
  noting: "trabajando",
  trastienda: "trabajando",

  thinking: "duda",
  waiting: "duda",
  arranque: "duda",
  vinculando: "duda",

  listening: "hablando",
  speaking: "hablando",

  hacking: "ejecutando",
  handling: "ejecutando",
  launching: "ejecutando",
  sending: "ejecutando",
  reaching: "ejecutando",

  searching: "buscando",
  browsing: "buscando",
  rummaging: "buscando",
  peeking: "buscando",
};

/** Acepta `string` porque el servidor puede desplegar un estado antes que la UI. */
export const familyOf = (state: FaceState | string): CompanionFamily =>
  FAMILY_BY_STATE[state as FaceState] ?? "reposo";
