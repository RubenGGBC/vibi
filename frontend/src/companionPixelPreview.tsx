import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import { PixelVibi } from "./components/PixelVibi";
import { createCompanionScene } from "./lib/face/companion/scene";
import type { FaceState } from "./lib/face/estados";
import "./styles/companion.css";
import "./styles/companion-pixel-preview.css";

const moods = [
  { label: "Reposo", state: "idle", hint: "Aquí, contigo." },
  { label: "Recelo", state: "recelo", hint: "Un momento…" },
  { label: "Contenta", state: "pleased", hint: "¡Eso es!" },
  { label: "Trabajando", state: "working", hint: "Estoy en ello." },
  { label: "Duda", state: "thinking", hint: "Déjame pensar." },
  { label: "Hablando", state: "speaking", hint: "Te cuento." },
  { label: "Ejecutando", state: "hacking", hint: "En marcha." },
  { label: "Buscando", state: "searching", hint: "A ver qué encuentro." },
] as const satisfies ReadonlyArray<{ label: string; state: FaceState; hint: string }>;

function OriginalVibi({ state }: { state: FaceState }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const scene = createCompanionScene(host.current, { frozen: true, morphs: false });
    scene.setState(state);
    scene.dibujar(1 / 60);
    return () => scene.dispose();
  }, [state]);
  return <div className="pixel-original face-canvas-companion" ref={host} aria-label="Vibi original" role="img" />;
}

function Preview() {
  const [selected, setSelected] = useState<(typeof moods)[number]>(moods[0]);
  const [background, setBackground] = useState<"dark" | "light">("dark");

  return (
    <main className="pixel-lab">
      <header className="pixel-topbar">
        <div className="pixel-wordmark"><span className="pixel-mark">✳</span> VIBI<span className="pixel-wordmark-dot">.</span></div>
        <span className="pixel-top-note">ESTUDIO DE MASCOTA / 01</span>
        <span className="pixel-top-badge"><span /> PROTOTIPO</span>
      </header>

      <div className="pixel-content">
        <section className="pixel-intro">
          <div>
            <p className="pixel-eyebrow">UNA NUEVA CARA PARA EL ESCRITORIO <span>↗</span></p>
            <h1>La misma Vibi.<br /><em>Píxel a píxel.</em></h1>
          </div>
          <p className="pixel-intro-copy">Su silueta original, sus ojos y sus llamitas, ahora en una cuadrícula de píxeles. Prueba sus gestos sobre un escritorio claro u oscuro.</p>
        </section>

        <section className="pixel-workbench" aria-label="Vista de prueba de Vibi pixel art">
          <div className={`pixel-desktop pixel-desktop--${background}`}>
            <div className="pixel-desktop-top"><span>VISTA DE ESCRITORIO</span><span>AMPLIACIÓN <b>× 2</b></span></div>
            <div className="pixel-desktop-centre">
              <div className="pixel-desktop-crosshair" aria-hidden="true" />
              <div className="pixel-desktop-pet" title={`Vibi: ${selected.label}`}>
                <PixelVibi state={selected.state} animated />
              </div>
              <div className="pixel-desktop-label"><span className="pixel-led" /> VIBI ESTÁ AQUÍ</div>
            </div>
            <div className="pixel-desktop-bottom">
              <span>01 — COMPANION FLOTANTE · TAMAÑO REAL ABAJO</span>
              <div className="pixel-background-switch" aria-label="Fondo del escritorio">
                <button type="button" aria-pressed={background === "dark"} onClick={() => setBackground("dark")}>Oscuro</button>
                <button type="button" aria-pressed={background === "light"} onClick={() => setBackground("light")}>Claro</button>
              </div>
            </div>
          </div>

          <aside className="pixel-controls">
            <div className="pixel-controls-heading"><span>EXPRESIONES</span><span>01 / 08</span></div>
            <h2>Una cara para<br />cada momento.</h2>
            <p>Selecciona un gesto para verlo en el escritorio y compararlo con el original.</p>
            <div className="pixel-mood-grid">
              {moods.map((mood, index) => (
                <button
                  key={mood.state}
                  type="button"
                  className={selected.state === mood.state ? "is-selected" : ""}
                  aria-pressed={selected.state === mood.state}
                  onClick={() => setSelected(mood)}
                >
                  <span className="pixel-mood-number">0{index + 1}</span>
                  <span>{mood.label}</span>
                  <span className="pixel-mood-arrow">↗</span>
                </button>
              ))}
            </div>
            <div className="pixel-current"><span>AHORA MISMO</span><strong>{selected.hint}</strong></div>
          </aside>
        </section>

        <section className="pixel-comparison" aria-label="Comparación con la mascota original">
          <div className="pixel-comparison-intro"><span>EL PARECIDO</span><h2>De curva<br />a cuadrícula.</h2><p>La silueta se mantiene; cambian el trazo y el ritmo. Así se ven las dos a la misma talla.</p></div>
          <div className="pixel-comparison-card"><span>01 / ORIGINAL</span><OriginalVibi state={selected.state} /><strong>La de siempre</strong></div>
          <div className="pixel-comparison-card pixel-comparison-card--new"><span>02 / PIXEL ART</span><PixelVibi state={selected.state} /><strong>La nueva versión <i>↗</i></strong></div>
        </section>
        <footer className="pixel-footer"><span>VIBI / ENSAYO VISUAL</span><span>LA CARA ORIGINAL · 105 × 90 PÍXELES</span></footer>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<Preview />);
