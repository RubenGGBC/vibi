import { ArrowUp } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";

interface MessageComposerProps {
  label: string;
  placeholder: string;
  submitLabel: string;
  pending?: boolean;
  autoFocus?: boolean;
  onSubmit: (text: string) => Promise<void> | void;
}

export function MessageComposer({
  label,
  placeholder,
  submitLabel,
  pending = false,
  autoFocus = false,
  onSubmit,
}: MessageComposerProps) {
  const [text, setText] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const clean = text.trim();
    if (!clean || pending) return;
    try {
      await onSubmit(clean);
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

  return (
    <form className="message-composer" onSubmit={submit}>
      <label className="sr-only" htmlFor={`composer-${label.replaceAll(" ", "-")}`}>
        {label}
      </label>
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
        disabled={pending || !text.trim()}
        aria-label={submitLabel}
      >
        <ArrowUp size={19} />
      </button>
    </form>
  );
}
