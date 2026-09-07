import { ArrowUp, Paperclip, X } from "lucide-react";
import {
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import type { UserFile } from "../types";

interface MessageComposerProps {
  label: string;
  placeholder: string;
  submitLabel: string;
  pending?: boolean;
  autoFocus?: boolean;
  onSubmit: (text: string) => Promise<void> | void;
  /**
   * Los adjuntos del mensaje en curso. Si no se pasa `onAdjuntar`, el clip no
   * aparece: hay compositores —la entrevista, la cara— donde adjuntar no
   * significa nada.
   */
  adjuntos?: UserFile[];
  onAdjuntar?: (archivos: FileList) => void;
  onQuitarAdjunto?: (fileId: string) => void;
  subiendoAdjunto?: boolean;
  errorAdjunto?: string | null;
}

export function MessageComposer({
  label,
  placeholder,
  submitLabel,
  pending = false,
  autoFocus = false,
  onSubmit,
  adjuntos = [],
  onAdjuntar,
  onQuitarAdjunto,
  subiendoAdjunto = false,
  errorAdjunto = null,
}: MessageComposerProps) {
  const [text, setText] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  // Con adjuntos, un mensaje vacío sigue siendo un mensaje: «mira esto» está
  // en el archivo, no en el texto.
  const puedeEnviar = Boolean(text.trim() || adjuntos.length);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!puedeEnviar || pending) return;
    try {
      await onSubmit(text.trim() || `Te adjunto ${adjuntos.length === 1 ? "un archivo" : "unos archivos"}.`);
      setText("");
    } catch {
      // La pantalla muestra el error y el texto queda disponible para corregirlo.
    }
  };
  const keyboardSubmit = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };
  const elegir = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files?.length) onAdjuntar?.(event.target.files);
    // Sin esto, volver a elegir el mismo archivo no dispara `change`.
    event.target.value = "";
  };

  return (
    <form className="message-composer" onSubmit={submit}>
      <label className="sr-only" htmlFor={`composer-${label.replaceAll(" ", "-")}`}>
        {label}
      </label>
      {(adjuntos.length > 0 || subiendoAdjunto || errorAdjunto) && (
        <ul className="composer-adjuntos" aria-label="Archivos adjuntos">
          {adjuntos.map((archivo) => (
            <li key={archivo.id} className="composer-adjunto">
              <Paperclip size={13} aria-hidden />
              <span>{archivo.name}</span>
              <button
                type="button"
                aria-label={`Quitar ${archivo.name}`}
                onClick={() => onQuitarAdjunto?.(archivo.id)}
              >
                <X size={13} />
              </button>
            </li>
          ))}
          {subiendoAdjunto && <li className="composer-adjunto pendiente">Subiendo…</li>}
          {errorAdjunto && (
            <li className="composer-adjunto fallo" role="alert">{errorAdjunto}</li>
          )}
        </ul>
      )}
      {onAdjuntar && (
        <>
          <input
            ref={fileInput}
            className="sr-only"
            type="file"
            multiple
            onChange={elegir}
            aria-label="Elegir archivos para adjuntar"
          />
          <button
            type="button"
            className="composer-attach"
            aria-label="Adjuntar archivo"
            disabled={pending || subiendoAdjunto}
            onClick={() => fileInput.current?.click()}
          >
            <Paperclip size={18} />
          </button>
        </>
      )}
      <textarea
        id={`composer-${label.replaceAll(" ", "-")}`}
        autoFocus={autoFocus}
        rows={2}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={keyboardSubmit}
        placeholder={placeholder}
      />
      <button
        type="submit"
        className="composer-submit"
        disabled={pending || !puedeEnviar}
        aria-label={submitLabel}
      >
        <ArrowUp size={19} />
      </button>
    </form>
  );
}
