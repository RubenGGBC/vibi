import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Globe, Terminal, Ellipsis, Mic, X } from "lucide-react";
import type { FaceState, Senales } from "../lib/face";
import { FoxVibi } from "./FoxVibi";
import { MascotaChat } from "./MascotaChat";
import "../styles/notch-companion.css";

export function NotchCompanion({ state, senales, copy, expanded, onExpand, voiceActive, onVoice, onEndVoice, onIniciarSesion }: {
  state: FaceState; senales: Senales; copy: string; expanded: boolean;
  onExpand: (value: boolean) => void; voiceActive: boolean; onVoice: () => void;
  onEndVoice: () => void; onIniciarSesion: () => void;
}) {
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const focused = useRef(false);
  const dismissed = useRef(false);
  const expandedRef = useRef(expanded);
  useEffect(() => { expandedRef.current = expanded; }, [expanded]);
  const cancelClose = () => { clearTimeout(closeTimer.current); closeTimer.current = undefined; };
  const reveal = () => { cancelClose(); if (!dismissed.current) onExpand(true); };
  const scheduleClose = () => {
    if (focused.current || closeTimer.current) return;
    closeTimer.current = setTimeout(() => { closeTimer.current = undefined; onExpand(false); }, 650);
  };
  useEffect(() => {
    let stopped = false;
    let pollTimer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const near = await invoke<boolean>("notch_pointer_near", { expanded: expandedRef.current });
        if (stopped) return;
        if (near) reveal();
        else { dismissed.current = false; scheduleClose(); }
      } catch { /* Pointer events remain available in browser previews. */ }
      if (!stopped) pollTimer = setTimeout(() => void poll(), 80);
    };
    const blur = () => { focused.current = false; };
    window.addEventListener("blur", blur);
    void poll();
    return () => { stopped = true; clearTimeout(pollTimer); cancelClose(); window.removeEventListener("blur", blur); };
    // The polling loop reads the current expansion from a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onExpand]);
  const [sugerencia, setSugerencia] = useState("");
  const [error, setError] = useState("");
  const suggest = (text: string) => { setSugerencia(text); onExpand(true); };
  return (
    <main
      className={`notch-companion ${expanded ? "is-expanded" : "is-hidden"}`}
      onPointerEnter={reveal} onPointerLeave={scheduleClose}
      onFocusCapture={() => { focused.current = true; cancelClose(); }}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) focused.current = false;
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          dismissed.current = true; focused.current = false; cancelClose();
          (document.activeElement as HTMLElement | null)?.blur(); onExpand(false);
        }
      }}
    >
      {!expanded && <button className="notch-reveal" aria-label="Desplegar Vibi" onClick={() => { dismissed.current = false; reveal(); }} onFocus={reveal} />}
      <div className="notch-content" inert={!expanded} aria-hidden={!expanded}>
        <button className="notch-fox" title={error || copy} aria-label="Abrir consola de Vibi" onClick={() => { void invoke("open_panel").catch(() => setError("No se pudo abrir la consola")); }}><FoxVibi state={state} senales={senales} /></button>
        <span className="notch-status" title={error || copy}><i />Vibi</span>
        <MascotaChat compact autoFocus={false} sugerencia={sugerencia} onCerrar={() => onExpand(false)} onIniciarSesion={onIniciarSesion} />
        <nav aria-label="Acciones de Vibi">
          <button className={state === "browsing" || state === "searching" ? "selected" : ""} title="Buscar en internet" aria-label="Buscar en internet" onClick={() => suggest("Busca en internet: ")}><Globe /></button>
          <button className={state === "hacking" ? "selected" : ""} title="Terminal" aria-label="Pedir una tarea de terminal" onClick={() => suggest("Ayúdame con el terminal: ")}><Terminal /></button>
          <button title={voiceActive ? "Terminar voz" : "Hablar"} aria-label={voiceActive ? "Terminar conversación" : "Hablar con Vibi"} onClick={voiceActive ? onEndVoice : onVoice}>{voiceActive ? <X /> : <Mic />}</button>
          <button title="Abrir consola" aria-label="Abrir consola" onClick={() => { void invoke("open_panel").catch(() => setError("No se pudo abrir la consola")); }}><Ellipsis /></button>
        </nav>
        {error && <span className="notch-sr" role="alert">{error}</span>}
      </div>
    </main>
  );
}
