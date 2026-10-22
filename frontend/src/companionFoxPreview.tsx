import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowDown, ArrowUpRight, Check, ChevronRight, Maximize2, Pause, Play, RotateCcw } from "lucide-react";
import { FOX_HEIGHT, FOX_WIDTH, loadFoxSprites, type FoxSprites } from "./lib/foxSprites";
import "./styles/companion-fox-preview.css";

const gestures = [
  { name: "Parpadeo", english: "Idle blink", description: "Un pequeño parpadeo. Sigo aquí, contigo.", duration: 1600 },
  { name: "Estiramiento", english: "Stretch", description: "Una pausa para estirar. Y seguimos.", duration: 2000 },
  { name: "Tocar cara", english: "Face touch", description: "Déjame pensar un momentito…", duration: 1800 },
] as const;

function Sprite({ image, label, className = "" }: { image?: HTMLCanvasElement; label: string; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !image) return;
    const context = canvas.getContext("2d")!;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.imageSmoothingEnabled = false;
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
  }, [image]);
  return <canvas ref={ref} width={FOX_WIDTH} height={FOX_HEIGHT} role="img" aria-label={label} className={`fox-sprite ${className}`} />;
}

function FoxPreview() {
  const [sprites, setSprites] = useState<FoxSprites>();
  const [error, setError] = useState("");
  const [gesture, setGesture] = useState(0);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(() => !window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [auto, setAuto] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [zoom, setZoom] = useState(2);
  const [background, setBackground] = useState("studio");
  const [visible, setVisible] = useState(() => !document.hidden);
  const stageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    loadFoxSprites().then((result) => { if (active) setSprites(result); }).catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!playing || !sprites || !visible) return;
    const timer = window.setTimeout(() => {
      if (frame < 7) setFrame(frame + 1);
      else {
        setFrame(0);
        if (auto) setGesture((gesture + 1) % gestures.length);
      }
    }, ((frame === 7 ? 1000 : gestures[gesture].duration / 8) / speed));
    return () => window.clearTimeout(timer);
  }, [playing, sprites, frame, gesture, speed, auto, visible]);

  // Resume from the same pose when returning to a backgrounded tab.
  useEffect(() => {
    const updateVisibility = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  const select = (index: number) => { setGesture(index); setFrame(0); setAuto(false); };
  const current = gestures[gesture];

  return <main className="fox-lab">
    <header className="fox-header">
      <a className="fox-wordmark" href="/companion-fox.html" aria-label="Vibi, inicio de la demo"><span>✳</span> vibi<span className="fox-red">.</span></a>
      <span className="fox-mono fox-header-note">COMPANION DESIGN LAB <span>/</span> 002</span>
      <span className="fox-badge"><i /> DEMO INTERACTIVA</span>
    </header>

    <section className="fox-intro">
      <div><p className="fox-eyebrow">UN PEQUEÑO COMPAÑERO. MUCHA PERSONALIDAD.</p><h1>Hola, soy Vibi<span>.</span><br /><em>Ahora tengo magia.</em></h1></div>
      <div className="fox-intro-note"><span className="fox-mono">NUEVA FORMA, MISMA ESENCIA <ArrowUpRight size={16} /></span><p>Un zorro, un sombrero imposible y esos pequeños gestos que lo hacen sentir vivo.</p><a href="#motion">Conoce sus movimientos <ArrowDown size={14} /></a></div>
    </section>

    <section className="fox-workbench" id="motion" aria-label="Laboratorio de animaciones">
      <div className={`fox-stage fox-stage--${background}`} ref={stageRef}>
        <div className="fox-stage-top fox-mono"><span><i /> LIVE PREVIEW</span><button type="button" title="Pantalla completa" aria-label="Ver escenario en pantalla completa" onClick={() => {
          if (document.fullscreenElement) void document.exitFullscreen().catch(() => setError("No se ha podido salir de pantalla completa."));
          else void stageRef.current?.requestFullscreen().catch(() => setError("Este navegador no permite pantalla completa."));
        }}><Maximize2 size={16} /></button></div>
        <div className="fox-stage-center">
          <div className="fox-orbit" aria-hidden="true" />
          <button className="fox-pet" type="button" style={{ width: FOX_WIDTH * zoom, height: FOX_HEIGHT * zoom }} aria-label="Tocar a Vibi: animar gesto de tocar cara" onClick={() => { select(2); setPlaying(true); }}>
            <Sprite image={sprites?.animations[gesture][frame]} label={`Vibi: ${current.name}, fotograma ${frame + 1}`} />
          </button>
          <div className="fox-stage-caption"><span className="fox-mono">VIBI, EL PEQUEÑO MAGO</span><span>{sprites ? current.description : "Preparando un poco de magia…"}</span></div>
          {error && <p role="alert" className="fox-error">{error}</p>}
        </div>
        <div className="fox-stage-bottom fox-mono"><div className="fox-swatches" aria-label="Fondo del escenario">{["studio", "light", "grid"].map((bg, i) => <button key={bg} type="button" className={`fox-swatch fox-swatch--${bg}`} aria-label={["Fondo oscuro", "Fondo claro", "Cuadrícula de transparencia"][i]} aria-pressed={background === bg} onClick={() => setBackground(bg)}>{background === bg && <Check size={11} />}</button>)}<span>FONDO</span></div><button type="button" className="fox-zoom" onClick={() => setZoom(zoom === 2 ? 1 : 2)}>ZOOM <b>×{zoom}</b></button></div>
      </div>

      <aside className="fox-panel">
        <div className="fox-panel-heading fox-mono"><span>BIBLIOTECA DE GESTOS</span><span>01—03</span></div>
        <h2>Pequeños gestos.<br />Un Vibi muy vivo.</h2>
        <p className="fox-panel-copy">Tres animaciones dibujadas píxel a píxel. Elige una y dale al play.</p>
        <div className="fox-gestures">{gestures.map((item, index) => <button key={item.name} className={gesture === index ? "is-active" : ""} aria-pressed={gesture === index} onClick={() => select(index)} type="button"><span className="fox-gesture-index fox-mono">0{index + 1}</span><span><strong>{item.name}</strong><small>{item.english} · 8 frames</small></span><ChevronRight size={17} /></button>)}</div>
        <label className="fox-auto"><span><strong>Modo automático</strong><small>Un gesto detrás de otro</small></span><input type="checkbox" checked={auto} onChange={(event) => setAuto(event.target.checked)} /><span className="fox-switch" aria-hidden="true" /></label>
        <div className="fox-playback"><button type="button" className="fox-play" disabled={!sprites} onClick={() => setPlaying(!playing)}>{playing ? <Pause size={16} /> : <Play size={16} />}{playing ? "Pausar" : "Reproducir"}</button><button type="button" className="fox-restart" aria-label="Reiniciar animación" title="Reiniciar" onClick={() => setFrame(0)}><RotateCcw size={16} /></button><label className="fox-speed"><span className="fox-mono">VELOCIDAD</span><select value={speed} onChange={(event) => setSpeed(Number(event.target.value))} aria-label="Velocidad de reproducción"><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={1.5}>1.5×</option><option value={2}>2×</option></select></label></div>
        <div className="fox-panel-foot fox-mono"><i /> {playing ? "ANIMACIÓN EN CURSO" : "ANIMACIÓN EN PAUSA"}<span>0{frame + 1} / 08</span></div>
      </aside>
    </section>

    <section className="fox-timeline" aria-label="Fotogramas de la animación">
      <div className="fox-timeline-title"><div><span className="fox-eyebrow">EL MOVIMIENTO, AL DETALLE</span><h2>{current.name}<span> / {current.english}</span></h2></div><span className="fox-mono">8 FOTOGRAMAS <span className="fox-divider">/</span> SELECCIONA PARA INSPECCIONAR</span></div>
      <div className="fox-frames">{Array.from({ length: 8 }, (_, index) => <button key={index} type="button" className={frame === index ? "is-active" : ""} aria-label={`Ver fotograma ${index + 1}`} aria-pressed={frame === index} onClick={() => { setPlaying(false); setFrame(index); }}><Sprite image={sprites?.animations[gesture][index]} label={`${current.name}, pose ${index + 1}`} /><span className="fox-mono">0{index + 1}<i /></span></button>)}</div>
    </section>

    <section className="fox-original"><div><p className="fox-eyebrow">EL PUNTO DE PARTIDA</p><h2>Del primer píxel<br />al primer parpadeo.</h2><p>El diseño original es la referencia. La lámina de animaciones le da sus primeros tres gestos.</p><span className="fox-mono">SOMBRERO ROJO. ESPÍRITU CURIOSO.</span></div><div className="fox-original-image">{sprites && <canvas width={680} height={820} ref={(canvas) => { if (canvas) canvas.getContext("2d")!.drawImage(sprites.portrait, 0, 0); }} role="img" aria-label="Diseño original de Vibi: zorro de píxel art con sombrero rojo de mago" />}<span className="fox-mono">01 / SPRITE ORIGINAL</span></div></section>
    <footer className="fox-footer fox-mono"><span>VIBI <span className="fox-red">✳</span> HECHO PARA ACOMPAÑARTE</span><span>FOX MOTION STUDY / DEMO 002</span></footer>
  </main>;
}

createRoot(document.getElementById("root")!).render(<FoxPreview />);
