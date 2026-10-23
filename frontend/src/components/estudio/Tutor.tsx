import {
  ChevronLeft,
  ChevronRight,
  GraduationCap,
  Hand,
  MessageCircleQuestion,
  Mic,
  Send,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { useState, type FormEvent } from "react";

import type { Escena } from "../../lib/estudio/tipos";
import {
  elegidasEn,
  estadoPregunta,
  mensajeAlTerminar,
  mensajeNoLoEntiendo,
} from "../../lib/estudio/tutor";
import { narracionDePaso, type VozTutor } from "../../lib/estudio/vozTutor";
import { useFaceMood } from "../../lib/faceMood";
import { FoxVibi } from "../FoxVibi";
import { PreguntaCard } from "./Controles";

/**
 * Vibi dando la clase: el zorro, lo que acaba de decir, el paso en el que
 * estáis y dónde contestarle. Es el único sitio donde se explica: el chat
 * queda para ver la conversación entera.
 */
export function Tutor({
  escena,
  voz,
  vozActiva,
  onVozActiva,
  onIr,
}: {
  escena: Escena | undefined;
  voz: VozTutor;
  vozActiva: boolean;
  onVozActiva: (activa: boolean) => void;
  onIr: (indice: number) => void;
}) {
  const animo = useFaceMood(voz.estado, voz.estado === "listening" || voz.estado === "speaking");
  const [texto, setTexto] = useState("");
  const pensando = voz.estado === "thinking" && !voz.bocadillo;
  const escuchando = voz.estado === "listening";

  const enviar = (evento: FormEvent) => {
    evento.preventDefault();
    if (!texto.trim()) return;
    voz.preguntar(texto);
    setTexto("");
  };

  return (
    <section className={`estudio-tutor es-${voz.estado}`} aria-label="Vibi, tu tutor">
      <div className="estudio-tutor-cabeza">
        <button
          type="button"
          className="estudio-tutor-zorro"
          onClick={voz.puedeEscuchar ? voz.alternarMicro : undefined}
          disabled={!voz.puedeEscuchar || pensando}
          aria-label={escuchando ? "Enviar lo que he dicho" : "Hablarle a Vibi"}
          aria-pressed={escuchando}
        >
          <FoxVibi state={animo.cara} senales={animo.senales} />
        </button>
        <div className="estudio-tutor-bocadillo" aria-live="polite">
          {voz.error ? (
            <p className="estudio-tutor-error">{voz.error}</p>
          ) : escuchando ? (
            <p className="estudio-tutor-estado">Te escucho… toca al zorro para enviar.</p>
          ) : pensando ? (
            <p className="estudio-tutor-estado">
              {(voz.etiqueta || "Pensando").replace(/[.…]+$/, "")}
              <span className="estudio-tutor-puntos" aria-hidden="true" />
            </p>
          ) : voz.bocadillo ? (
            <>
              <p>{voz.bocadillo}</p>
              <button type="button" className="estudio-tutor-cerrar" onClick={voz.cerrarBocadillo} aria-label="Cerrar">
                <X size={14} />
              </button>
            </>
          ) : (
            <p className="estudio-tutor-estado">
              {escena?.pasos.length
                ? "Si algo no encaja, pregúntame o tócame para hablar."
                : "¿Qué quieres entender hoy? Te lo monto aquí."}
            </p>
          )}
        </div>
      </div>

      <div className="estudio-tutor-cuerpo">
        {escena && escena.pasos.length > 0 && (
          <PasoActual escena={escena} voz={voz} conVoz={vozActiva} onIr={onIr} />
        )}
      </div>

        <form className="estudio-tutor-entrada" onSubmit={enviar}>
          <input
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder={escena?.pasos.length ? "Pregúntale a Vibi sobre esto…" : "¿Qué quieres entender?"}
            aria-label="Pregúntale a Vibi"
            disabled={pensando}
          />
          <button type="submit" disabled={!texto.trim() || pensando} aria-label="Enviar">
            <Send size={15} />
          </button>
          {voz.puedeEscuchar && (
            <button
              type="button"
              className={escuchando ? "es-activo" : undefined}
              onClick={voz.alternarMicro}
              disabled={pensando}
              aria-label={escuchando ? "Enviar lo que he dicho" : "Hablar"}
            >
              <Mic size={15} />
            </button>
          )}
          <button
            type="button"
            className={vozActiva ? "es-activo" : undefined}
            onClick={() => onVozActiva(!vozActiva)}
            aria-pressed={vozActiva}
            aria-label={vozActiva ? "Silenciar a Vibi" : "Que Vibi hable"}
            title={vozActiva ? "Silenciar a Vibi" : "Que Vibi hable"}
          >
            {vozActiva ? <Volume2 size={15} /> : <VolumeX size={15} />}
          </button>
        </form>
    </section>
  );
}

function PasoActual({
  escena,
  voz,
  conVoz,
  onIr,
}: {
  escena: Escena;
  voz: VozTutor;
  conVoz: boolean;
  onIr: (indice: number) => void;
}) {
  const total = escena.pasos.length;
  const actual = Math.min(Math.max(escena.paso_actual, 0), total - 1);
  const paso = escena.pasos[actual];
  const ultimo = actual === total - 1;
  const pendiente = Boolean(
    paso.pregunta && !estadoPregunta(paso.pregunta, elegidasEn(escena, actual)).resuelta,
  );
  const ir = (indice: number) => {
    voz.cerrarBocadillo();
    onIr(indice);
  };
  return (
    <div className="estudio-paso" aria-label={`Paso ${actual + 1} de ${total}`}>
      <div className="estudio-paso-barra">
        <button type="button" disabled={actual === 0} onClick={() => ir(actual - 1)} aria-label="Paso anterior">
          <ChevronLeft size={16} />
        </button>
        <ol className="estudio-pasos-puntos">
          {escena.pasos.map((_, i) => (
            <li key={i}>
              <button
                type="button"
                className={i === actual ? "es-actual" : i < actual ? "es-hecho" : ""}
                aria-label={`Paso ${i + 1}`}
                aria-current={i === actual ? "step" : undefined}
                onClick={() => ir(i)}
              />
            </li>
          ))}
        </ol>
        <span className="estudio-pasos-cuenta">
          {actual + 1}/{total}
        </span>
        <button
          type="button"
          disabled={ultimo}
          className={pendiente ? "es-espera" : "es-siguiente"}
          title={pendiente ? "Antes, contesta la pregunta" : undefined}
          onClick={() => ir(actual + 1)}
          aria-label="Paso siguiente"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      {paso.idea && <p className="estudio-paso-idea">{paso.idea}</p>}
      <p className="estudio-paso-texto">{paso.texto}</p>
      {paso.tarea && (
        <p className="estudio-paso-tarea">
          <Hand size={14} /> <span>{paso.tarea}</span>
        </p>
      )}
      <PreguntaCard
        key={`${escena.version}-${actual}`}
        escena={escena}
        indice={actual}
        onPedirTutor={voz.preguntar}
        onDecir={voz.decir}
      />
      <div className="estudio-paso-acciones">
        {conVoz && (
          <button type="button" onClick={() => voz.decir(narracionDePaso(paso))}>
            <Volume2 size={13} /> Escuchar
          </button>
        )}
        <button type="button" onClick={() => voz.preguntar(mensajeNoLoEntiendo(escena, actual))}>
          <MessageCircleQuestion size={13} /> No lo entiendo
        </button>
        {ultimo && !pendiente && (
          <button type="button" className="es-destacado" onClick={() => voz.preguntar(mensajeAlTerminar(escena))}>
            <GraduationCap size={13} /> ¿Repasamos?
          </button>
        )}
      </div>
    </div>
  );
}
