import { useCallback, useState } from "react";

interface ConfirmState {
  message: string;
  resolve: (value: boolean) => void;
}

/**
 * Reemplazo de `window.confirm()`: en el companion de Tauri (WKWebView en
 * macOS) los diálogos JS nativos (alert/confirm/prompt) no están implementados
 * y se resuelven solos como `false` sin mostrar nada, así que cualquier botón
 * que dependiera de `window.confirm` quedaba muerto sin avisar. Este hook lo
 * sustituye por un diálogo propio que sí funciona en las dos superficies (PWA
 * y companion).
 */
export function useConfirm() {
  const [state, setState] = useState<ConfirmState | null>(null);

  const confirm = useCallback((message: string) => {
    return new Promise<boolean>((resolve) => {
      setState({ message, resolve });
    });
  }, []);

  const respond = (value: boolean) => {
    state?.resolve(value);
    setState(null);
  };

  const dialog = state ? (
    <div
      className="dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) respond(false);
      }}
    >
      <section
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-describedby="confirm-dialog-message"
      >
        <p id="confirm-dialog-message">{state.message}</p>
        <div className="confirm-dialog-actions">
          <button type="button" className="ghost-button" onClick={() => respond(false)}>
            Cancelar
          </button>
          <button type="button" className="primary-button" onClick={() => respond(true)}>
            Confirmar
          </button>
        </div>
      </section>
    </div>
  ) : null;

  return { confirm, dialog };
}
