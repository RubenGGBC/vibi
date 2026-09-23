import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/**
 * Devuelve el `localStorage` que jsdom ya traía, tapado por Node.
 *
 * Node 26 añadió un `localStorage` global propio que solo funciona si arrancas
 * el proceso con `--localstorage-file`. Vitest monta jsdom copiando sus globales
 * sobre `globalThis` salvo las que ya existen, así que esa clave de Node gana y
 * al leerla sale `undefined`: todo el que llamara a `localStorage.setItem`
 * reventaba con «Cannot read properties of undefined», y con él la suite entera
 * aunque jsdom estuviera perfectamente activo.
 *
 * Se repone a mano y solo cuando de verdad está rota, para que el día que Node
 * o Vitest lo arreglen esto se aparte solo en vez de seguir imponiendo el doble.
 */
const reponerAlmacenamiento = (nombre: "localStorage" | "sessionStorage") => {
  if (globalThis[nombre]) return;
  const datos = new Map<string, string>();
  const almacen: Storage = {
    get length() {
      return datos.size;
    },
    key: (indice) => [...datos.keys()][indice] ?? null,
    getItem: (clave) => datos.get(String(clave)) ?? null,
    setItem: (clave, valor) => void datos.set(String(clave), String(valor)),
    removeItem: (clave) => void datos.delete(String(clave)),
    clear: () => datos.clear(),
  };
  Object.defineProperty(globalThis, nombre, {
    value: almacen,
    configurable: true,
    writable: true,
  });
};

reponerAlmacenamiento("localStorage");
reponerAlmacenamiento("sessionStorage");

afterEach(() => cleanup());
