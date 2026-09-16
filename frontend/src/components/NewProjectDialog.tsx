import { X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

interface NewProjectDialogProps {
  pending: boolean;
  error?: string;
  onClose: () => void;
  onCreate: (nombre: string, descripcion: string) => Promise<void>;
}

export function NewProjectDialog({
  pending,
  error,
  onClose,
  onCreate,
}: NewProjectDialogProps) {
  const [nombre, setNombre] = useState("");
  const [descripcion, setDescripcion] = useState("");
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !pending) onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, pending]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!nombre.trim()) return;
    try {
      await onCreate(nombre.trim(), descripcion.trim());
    } catch {
      // La pantalla conserva lo escrito y muestra el error de la mutación.
    }
  };

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !pending) onClose();
      }}
    >
      <section
        className="clone-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="nuevo-proyecto-title"
      >
        <button
          className="icon-button dialog-close"
          onClick={onClose}
          disabled={pending}
          aria-label="Cerrar"
        >
          <X size={18} />
        </button>
        <p className="eyebrow">Nuevo proyecto</p>
        <h2 id="nuevo-proyecto-title">Crear un espacio</h2>
        <p>Una carpeta de trabajo donde subir archivos y guardar conversaciones.</p>
        <form onSubmit={submit}>
          <label htmlFor="proyecto-nombre">Nombre</label>
          <input
            id="proyecto-nombre"
            type="text"
            autoFocus
            maxLength={120}
            value={nombre}
            onChange={(event) => setNombre(event.target.value)}
            placeholder="Trabajo de fin de grado"
            required
          />
          <label htmlFor="proyecto-descripcion">De qué va (opcional)</label>
          <textarea
            id="proyecto-descripcion"
            rows={3}
            maxLength={2000}
            value={descripcion}
            onChange={(event) => setDescripcion(event.target.value)}
            placeholder="Lo que quieras recordar cuando lo abras dentro de un mes."
          />
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="primary-button" disabled={pending || !nombre.trim()}>
            {pending ? "Creando…" : "Crear proyecto"}
          </button>
        </form>
      </section>
    </div>
  );
}
