/**
 * La cara de Vibi.
 *
 * El personaje —chistera, antifaz y fuego— vive en `vibi/`: `rasgos.ts` lo que
 * no cambia, `formas.ts` los rasgos que morfan y `gestos.ts` el reparto de los
 * treinta y dos estados entre las ocho caras. `escena.ts` lo monta y lo mueve.
 *
 * **`bloub/`, `liquido.ts`, `antena.ts`, `puente.ts` y `ojos.ts` ya no los usa
 * nadie**: son la cara anterior, la masa con antena. Se quedan mientras se
 * comprueba la nueva contra los tres sitios donde se monta; en cuanto esté
 * dada por buena, se van con sus pruebas.
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
