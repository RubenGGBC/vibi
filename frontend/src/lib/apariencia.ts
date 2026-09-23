import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import type { AparienciaVibi } from "../types";
import { apiFetch } from "./api";

export const APARIENCIA_ORIGINAL: AparienciaVibi = {
  color_cara: "#FFFFFF",
  color_antifaz: "#0C0714",
  color_sombrero: "#F4121B",
  actualizada_en: 0,
};

export const aparienciaKey = ["apariencia-vibi"] as const;

export async function fetchApariencia(): Promise<AparienciaVibi> {
  return apiFetch<AparienciaVibi>("/api/apariencia");
}

export async function guardarApariencia(
  apariencia: Pick<AparienciaVibi, "color_cara" | "color_antifaz" | "color_sombrero">,
): Promise<AparienciaVibi> {
  return apiFetch<AparienciaVibi>("/api/apariencia", {
    method: "PUT",
    body: JSON.stringify(apariencia),
  });
}

const rgb = (hex: string): [number, number, number] => [
  Number.parseInt(hex.slice(1, 3), 16),
  Number.parseInt(hex.slice(3, 5), 16),
  Number.parseInt(hex.slice(5, 7), 16),
];

export const sombraDe = (hex: string, factor = 0.68): string => {
  const [r, g, b] = rgb(hex);
  return `#${[r, g, b]
    .map((canal) => Math.round(canal * factor).toString(16).padStart(2, "0"))
    .join("")}`;
};

export const resplandorDe = (hex: string): string => rgb(hex).join(" ");

/**
 * Esto corre dentro de un `useEffect` y no hay error boundary por encima, así
 * que un color que falte no desluce la ventana: la tumba entera. El cuerpo lo
 * manda el servidor, y que el tipo prometa los tres campos no obliga a que
 * lleguen —una migración a medias o un 200 incompleto bastan—, así que lo que
 * no venga se rellena con la identidad original.
 */
export function aplicarApariencia(apariencia: AparienciaVibi): void {
  // Un spread no bastaría: JSON distingue "el campo no viene" de "el campo
  // viene a null", y el segundo caso se cuela igual de roto.
  const color = (clave: keyof typeof APARIENCIA_ORIGINAL & `color_${string}`) =>
    typeof apariencia?.[clave] === "string"
      ? (apariencia[clave] as string)
      : APARIENCIA_ORIGINAL[clave];
  const color_cara = color("color_cara");
  const color_antifaz = color("color_antifaz");
  const color_sombrero = color("color_sombrero");
  const raiz = document.documentElement;
  raiz.style.setProperty("--vibi-identidad-cara", color_cara);
  raiz.style.setProperty("--vibi-identidad-antifaz", color_antifaz);
  raiz.style.setProperty("--vibi-identidad-sombrero", color_sombrero);
  raiz.style.setProperty(
    "--vibi-identidad-sombrero-sombra",
    sombraDe(color_sombrero),
  );
  raiz.style.setProperty(
    "--vibi-identidad-resplandor",
    resplandorDe(color_sombrero),
  );
}

export function limpiarApariencia(): void {
  const raiz = document.documentElement;
  for (const variable of [
    "--vibi-identidad-cara",
    "--vibi-identidad-antifaz",
    "--vibi-identidad-sombrero",
    "--vibi-identidad-sombrero-sombra",
    "--vibi-identidad-resplandor",
  ]) {
    raiz.style.removeProperty(variable);
  }
}

/** Mantiene la identidad del usuario aplicada a esta ventana completa. */
export function useAparienciaVibi(enabled = true) {
  const query = useQuery({
    queryKey: aparienciaKey,
    queryFn: fetchApariencia,
    enabled,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!enabled || !query.data) return undefined;
    aplicarApariencia(query.data);
    return limpiarApariencia;
  }, [enabled, query.data]);

  return query;
}
