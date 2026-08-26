import { VibiFace } from "./VibiFace";
import { useFaceMood } from "../lib/faceMood";
import type { FaceState } from "../lib/face";

/**
 * La cara, anclada arriba del rail.
 *
 * Es la pieza que sostiene la dirección C. Hasta ahora la cara vivía en una de
 * las ocho páginas de la consola —la pestaña «Cara» de la home—, así que si
 * estabas en Archivos no había forma de saber que Vibi llevaba siete pasos
 * navegando en el sobremesa. Aquí está siempre, y es lo que hace que la ventana
 * flotante y la consola sigan siendo **la misma cosa** en dos tallas y no dos
 * productos que casualmente comparten servidor.
 *
 * No abre canal propio: `useFaceMood` ya escucha el que reparte `useEvents`.
 */

/**
 * Lo que se lee cuando el ánimo no trae texto.
 *
 * `useFaceMood` deja el copy vacío a propósito cuando manda la conversación,
 * porque allí el texto lo pone el turno. Aquí no hay turno de voz —se le pasa
 * `idle`— así que los únicos huecos son estos dos, y un hueco de verdad
 * dejaría la franja sin decir nada la mayor parte del tiempo.
 */
const RESERVA: Partial<Record<FaceState, string>> = {
  idle: "En reposo",
  arranque: "Despertando",
};

export function RailFace() {
  // Sin sesión de voz: en la consola la cara cuenta lo que Vibi hace, no lo que
  // te está diciendo. Esa parte es del companion.
  const animo = useFaceMood("idle", false);
  const texto = animo.copy || RESERVA[animo.cara] || "";

  return (
    <div className={`rail-cara cara-${animo.cara}`}>
      <span className="rail-cara-vidrio" aria-hidden="true">
        <span className="rail-cara-halo" />
        <VibiFace state={animo.cara} senales={animo.senales} />
      </span>
      <p className="rail-cara-estado">{texto}</p>
      {/* Las fichas solo salen cuando tienen algo que decir. En reposo la fila
          entera no existe, en vez de quedarse a cero. */}
      {(animo.senales.pasos > 0 || animo.senales.remoto) && (
        <p className="rail-cara-fichas">
          {animo.senales.pasos > 0 && <span>Paso {animo.senales.pasos}</span>}
          {animo.senales.remoto && <span>{animo.senales.remoto}</span>}
        </p>
      )}
    </div>
  );
}
