/**
 * La cara de Vibi.
 *
 * La geometría y el movimiento son de `bloub/`, código de terceros vendorizado
 * —ver `bloub/PROCEDENCIA.md`—. Lo de Vibi es lo que hay alrededor: la antena,
 * los veintitrés gestos con significado y las señales vivas del turno.
 *
 * Quien la usa solo necesita esto; el resto es cocina de dentro.
 */

export { crearEscenaCara, type FaceScene, type OpcionesEscena } from "./escena";
export {
  ESTADOS,
  type FacePerfil,
  type FaceState,
  type FaceToolState,
  type FaceVoiceState,
} from "./estados";
export { SENALES_QUIETAS, type Senales } from "./modificadores";
