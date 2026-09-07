import { useState } from "react";

import { ApiError, apiFetch } from "./api";
import type { UserFile } from "../types";

/**
 * Los archivos que acompañan al mensaje que se está escribiendo.
 *
 * Se suben en cuanto se eligen, no al enviar: así el envío es un id y no unos
 * megas, el mensaje sale igual de rápido lleve lo que lleve, y el archivo ya
 * está en tus archivos aunque al final no llegues a mandar nada.
 */
export interface Adjuntos {
  archivos: UserFile[];
  subiendo: boolean;
  error: string | null;
  añadir: (elegidos: FileList | globalThis.File[]) => Promise<void>;
  quitar: (fileId: string) => void;
  limpiar: () => void;
}

export function useAdjuntos(): Adjuntos {
  const [archivos, setArchivos] = useState<UserFile[]>([]);
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const añadir = async (elegidos: FileList | globalThis.File[]) => {
    const lista = Array.from(elegidos);
    if (!lista.length) return;
    setSubiendo(true);
    setError(null);
    try {
      for (const archivo of lista) {
        const data = new FormData();
        data.append("archivo", archivo);
        const subido = await apiFetch<UserFile>("/api/archivos", {
          method: "POST",
          body: data,
        });
        setArchivos((current) => [...current, subido]);
      }
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo adjuntar el archivo.",
      );
    } finally {
      setSubiendo(false);
    }
  };

  return {
    archivos,
    subiendo,
    error,
    añadir,
    quitar: (fileId) =>
      setArchivos((current) => current.filter((file) => file.id !== fileId)),
    limpiar: () => {
      setArchivos([]);
      setError(null);
    },
  };
}
