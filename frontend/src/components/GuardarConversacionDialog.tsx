import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../lib/api";
import {
  guardarConversacionActiva,
  listarProyectos,
  projectConversationsKey,
  projectsKey,
} from "../lib/proyectos";
import type { SavedConversation } from "../types";

interface GuardarConversacionDialogProps {
  onClose: () => void;
  onGuardada: (conversacion: SavedConversation) => void;
}

/**
 * Guarda la conversación en curso dentro de un proyecto.
 *
 * El título es opcional a propósito: pedirlo justo cuando alguien acaba de
 * terminar de escribir es fricción, y el servidor sabe sacar uno del primer
 * mensaje del hilo.
 */
export function GuardarConversacionDialog({
  onClose,
  onGuardada,
}: GuardarConversacionDialogProps) {
  const client = useQueryClient();
  const [projectId, setProjectId] = useState("");
  const [titulo, setTitulo] = useState("");
  const proyectos = useQuery({ queryKey: projectsKey, queryFn: listarProyectos });

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const guardar = useMutation({
    mutationFn: () =>
      guardarConversacionActiva(projectId || null, titulo.trim() || undefined),
    onSuccess: async (conversacion) => {
      await client.invalidateQueries({ queryKey: projectsKey });
      if (conversacion.project_id) {
        await client.invalidateQueries({
          queryKey: projectConversationsKey(conversacion.project_id),
        });
      }
      onGuardada(conversacion);
    },
  });

  const disponibles = proyectos.data?.detalles ?? [];
  const submit = (event: FormEvent) => {
    event.preventDefault();
    guardar.mutate();
  };

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !guardar.isPending) onClose();
      }}
    >
      <section
        className="clone-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="guardar-title"
      >
        <button
          className="icon-button dialog-close"
          onClick={onClose}
          disabled={guardar.isPending}
          aria-label="Cerrar"
        >
          <X size={18} />
        </button>
        <p className="eyebrow">Esta conversación</p>
        <h2 id="guardar-title">Guardar en un proyecto</h2>
        <p>Seguirás hablando en ella; solo pasa a poder encontrarse después.</p>
        <form onSubmit={submit}>
          <label htmlFor="guardar-proyecto">Proyecto</label>
          <select
            id="guardar-proyecto"
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
          >
            <option value="">Sin proyecto</option>
            {disponibles.map((proyecto) => (
              <option key={proyecto.id} value={proyecto.id}>
                {proyecto.nombre}
              </option>
            ))}
          </select>
          <label htmlFor="guardar-titulo">Título (opcional)</label>
          <input
            id="guardar-titulo"
            type="text"
            value={titulo}
            maxLength={200}
            onChange={(event) => setTitulo(event.target.value)}
            placeholder="Si lo dejas vacío, lo saco del primer mensaje"
          />
          {proyectos.isError && (
            <p className="form-error" role="alert">
              No se pudieron leer tus proyectos.
            </p>
          )}
          {guardar.error && (
            <p className="form-error" role="alert">
              {guardar.error instanceof ApiError
                ? guardar.error.message
                : "No se pudo guardar la conversación."}
            </p>
          )}
          <button className="primary-button" disabled={guardar.isPending}>
            {guardar.isPending ? "Guardando…" : "Guardar conversación"}
          </button>
        </form>
      </section>
    </div>
  );
}
