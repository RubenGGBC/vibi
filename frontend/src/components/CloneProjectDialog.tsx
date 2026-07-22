import { X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

interface CloneProjectDialogProps {
  pending: boolean;
  error?: string;
  onClose: () => void;
  onClone: (url: string) => Promise<void>;
}

export function CloneProjectDialog({
  pending,
  error,
  onClose,
  onClone,
}: CloneProjectDialogProps) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !pending) onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, pending]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!url.trim()) return;
    try {
      await onClone(url.trim());
    } catch {
      // La pantalla conserva URL y muestra el error de la mutación.
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !pending) onClose();
    }}>
      <section className="clone-dialog" role="dialog" aria-modal="true" aria-labelledby="clone-title">
        <button className="icon-button dialog-close" onClick={onClose} disabled={pending} aria-label="Cerrar"><X size={18} /></button>
        <p className="eyebrow">Nuevo proyecto</p>
        <h2 id="clone-title">Clonar repositorio</h2>
        <p>Pega una URL HTTPS de GitHub o una URL SSH de un host Git conocido.</p>
        <form onSubmit={submit}>
          <label htmlFor="clone-url">URL del repositorio</label>
          <input
            id="clone-url"
            type="text"
            autoFocus
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://github.com/equipo/proyecto.git"
            required
          />
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="primary-button" disabled={pending || !url.trim()}>
            {pending ? "Clonando…" : "Clonar repo"}
          </button>
        </form>
      </section>
    </div>
  );
}
