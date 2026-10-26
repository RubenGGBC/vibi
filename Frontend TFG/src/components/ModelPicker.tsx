import { Cpu, X } from "lucide-react";
import { useState } from "react";

/**
 * Un modelo de `agy`, tal como los sirve `/api/agy/modelos`.
 *
 * `effort_en_el_nombre` decide si al elegirlo hay que preguntar el effort
 * aparte: los que ya lo llevan en el nombre —`gemini-3.8-flash-high`— lo
 * rechazan como parámetro, la propia CLI lo hace.
 */
export interface AgyModelo {
  id: string;
  etiqueta: string;
  effort_en_el_nombre: boolean;
}

const EFFORTS = ["low", "medium", "high"] as const;

/**
 * Botón que compone `/model …` y lo entrega a quien lo vaya a mandar.
 *
 * No sabe pedir la lista ni mandar el mensaje: eso lo hace quien lo usa —ver
 * `ChatPanel`—, igual que `MessageComposer` no sabe enviar nada por su
 * cuenta. Así se prueba con datos de mentira, sin un servidor detrás.
 */
export function ModelPicker({
  modelos,
  cargando,
  error,
  onElegir,
  onAbrir,
  disabled = false,
}: {
  modelos: AgyModelo[];
  cargando: boolean;
  error: string | null;
  onElegir: (comando: string) => void;
  /** Se llama solo al abrir, nunca al cerrar: pedir la lista de nuevo cada
   * vez que se cierra el popover no aporta nada y `agy models` no es
   * gratis. */
  onAbrir?: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  // El modelo para el que se está preguntando el effort, o ninguno. Vive
  // aparte de `open` porque cerrar el popover tiene que olvidarlo: si no,
  // reabrirlo mostraría los tres botones de effort sin que se hubiera vuelto
  // a pulsar el modelo.
  const [effortPara, setEffortPara] = useState<string | null>(null);

  const cerrar = () => {
    setOpen(false);
    setEffortPara(null);
  };

  const elegir = (comando: string) => {
    onElegir(comando);
    cerrar();
  };

  return (
    <div className="chat-tool-picker">
      <button
        type="button"
        className={`chat-control-button${open ? " is-active" : ""}`}
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={() =>
          setOpen((current) => {
            if (!current) onAbrir?.();
            return !current;
          })
        }
        disabled={disabled}
      >
        <Cpu size={15} />
        Modelo
      </button>
      {open && (
        <div
          className="chat-tool-popover"
          role="listbox"
          aria-label="Elegir el modelo de agy"
        >
          <div className="chat-tool-popover-heading">
            <div>
              <strong>Modelo de agy</strong>
              <small>Se aplica al momento, en todas tus conversaciones con agy.</small>
            </div>
            <button type="button" onClick={cerrar} aria-label="Cerrar selector de modelo">
              <X size={15} />
            </button>
          </div>
          {cargando && <p className="chat-tool-empty">Preguntando a agy…</p>}
          {error && <p className="chat-tool-empty">{error}</p>}
          <div className="chat-tool-options">
            <button type="button" onClick={() => elegir("/model default")}>
              <span>
                <strong>Por defecto</strong>
                <small>El que traiga configurado el servidor</small>
              </span>
            </button>
            {modelos.map((modelo) =>
              effortPara === modelo.id ? (
                <div key={modelo.id} className="chat-tool-options">
                  <span>
                    <strong>{modelo.etiqueta}</strong>
                    <small>Effort:</small>
                  </span>
                  {EFFORTS.map((effort) => (
                    <button
                      key={effort}
                      type="button"
                      onClick={() => elegir(`/model ${modelo.id} ${effort}`)}
                    >
                      {effort}
                    </button>
                  ))}
                </div>
              ) : (
                <button
                  key={modelo.id}
                  type="button"
                  onClick={() =>
                    modelo.effort_en_el_nombre
                      ? elegir(`/model ${modelo.id}`)
                      : setEffortPara(modelo.id)
                  }
                >
                  <span>
                    <strong>{modelo.etiqueta}</strong>
                  </span>
                </button>
              ),
            )}
          </div>
        </div>
      )}
    </div>
  );
}
