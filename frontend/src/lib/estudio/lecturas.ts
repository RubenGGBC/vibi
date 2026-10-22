/**
 * Las lecturas en vivo de las simulaciones (t, θ, energía…).
 *
 * Cambian en cada fotograma, y pasarlas por el estado de React a 60 Hz
 * re-renderizaría la escena entera. Así que la simulación las deja aquí desde
 * su `useFrame` y el panel las recoge unas pocas veces por segundo.
 */
export type Filas = [string, string][];

const lecturas = new Map<string, { titulo: string; filas: Filas }>();

export function publicarLectura(id: string, titulo: string, filas: Filas): void {
  lecturas.set(id, { titulo, filas });
}

export function quitarLectura(id: string): void {
  lecturas.delete(id);
}

export function leerLecturas(): { id: string; titulo: string; filas: Filas }[] {
  return [...lecturas.entries()].map(([id, l]) => ({ id, ...l }));
}
