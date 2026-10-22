import {
  ChevronLeft,
  ChevronRight,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
} from "lucide-react";
import { useEffect, useState } from "react";

import { formatear } from "../../lib/estudio/ejes";
import { leerLecturas } from "../../lib/estudio/lecturas";
import type { Elemento, Escena, Grafo, Ordenacion, Paso } from "../../lib/estudio/tipos";
import { COLORES_ALGORITMO } from "./AlgoritmosVista";

export function Deslizadores({
  escena,
  valores,
  onCambio,
}: {
  escena: Escena;
  valores: Record<string, number>;
  onCambio: (id: string, valor: number) => void;
}) {
  if (!escena.parametros.length) return null;
  return (
    <div className="estudio-hud estudio-deslizadores" aria-label="Deslizadores">
      {escena.parametros.map((p) => (
        <label key={p.id} className="estudio-deslizador">
          <span className="estudio-deslizador-cabecera">
            <span>{p.etiqueta}</span>
            <b>
              {p.id} = {formatear(valores[p.id] ?? p.valor)}
            </b>
          </span>
          <input
            type="range"
            min={p.minimo}
            max={p.maximo}
            step={p.paso}
            value={valores[p.id] ?? p.valor}
            onChange={(e) => onCambio(p.id, Number(e.target.value))}
          />
        </label>
      ))}
    </div>
  );
}

const ORIGENES: Record<string, { texto: string; clase: string }> = {
  engine: { texto: "Calculado", clase: "es-verificado" },
  pubchem: { texto: "PubChem", clase: "es-verificado" },
  catalogo: { texto: "Catálogo", clase: "es-verificado" },
  modelo: { texto: "Vibi", clase: "es-redactado" },
};

/** Qué hay en la escena y de dónde sale cada cosa. */
export function Leyenda({ escena, visibles }: { escena: Escena; visibles: Set<string> }) {
  if (!escena.elementos.length) return null;
  return (
    <ul className="estudio-hud estudio-leyenda" aria-label="Elementos de la escena">
      {escena.elementos.map((e) => {
        const origen = ORIGENES[e.procedencia?.origen] ?? ORIGENES.modelo;
        return (
          <li key={e.id} className={visibles.has(e.id) ? "" : "es-oculto"}>
            <i style={{ background: e.color }} />
            <span className="estudio-leyenda-nombre">{e.etiqueta}</span>
            <span
              className={`estudio-procedencia ${origen.clase}`}
              title={e.procedencia?.detalle}
            >
              {e.procedencia?.url ? (
                <a href={e.procedencia.url} target="_blank" rel="noreferrer">
                  {origen.texto}
                </a>
              ) : (
                origen.texto
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

type ConReproductor = Grafo | Ordenacion;

export function tieneReproductor(e: Elemento): e is ConReproductor {
  return (e.tipo === "grafo" && Boolean(e.recorrido)) || e.tipo === "ordenacion";
}

function fotogramasDe(e: ConReproductor) {
  return e.tipo === "grafo" ? e.recorrido?.fotogramas ?? [] : e.fotogramas;
}

export function Reproductores({
  elementos,
  fotogramas,
  enReproduccion,
  onFotograma,
  onAlternar,
}: {
  elementos: ConReproductor[];
  fotogramas: Record<string, number>;
  enReproduccion: Record<string, boolean>;
  onFotograma: (id: string, indice: number) => void;
  onAlternar: (id: string) => void;
}) {
  if (!elementos.length) return null;
  return (
    <div className="estudio-hud estudio-reproductores">
      {elementos.map((e) => {
        const lista = fotogramasDe(e);
        const total = lista.length;
        const actual = Math.min(fotogramas[e.id] ?? 0, Math.max(total - 1, 0));
        const mensaje = lista[actual]?.mensaje ?? "";
        const titulo =
          e.tipo === "grafo"
            ? `${e.recorrido?.algoritmo.toUpperCase()} · ${e.etiqueta}`
            : e.etiqueta;
        return (
          <section key={e.id} className="estudio-reproductor" aria-label={`Reproductor de ${titulo}`}>
            <header>
              <b>{titulo}</b>
              <span>
                {actual + 1}/{total}
              </span>
            </header>
            <p className="estudio-reproductor-mensaje">{mensaje}</p>
            <div className="estudio-reproductor-botones">
              <button type="button" aria-label="Al principio" onClick={() => onFotograma(e.id, 0)}>
                <SkipBack size={14} />
              </button>
              <button type="button" aria-label="Anterior" onClick={() => onFotograma(e.id, Math.max(actual - 1, 0))}>
                <ChevronLeft size={14} />
              </button>
              <button type="button" className="es-principal" aria-label={enReproduccion[e.id] ? "Pausa" : "Reproducir"} onClick={() => onAlternar(e.id)}>
                {enReproduccion[e.id] ? <Pause size={14} /> : <Play size={14} />}
              </button>
              <button type="button" aria-label="Siguiente" onClick={() => onFotograma(e.id, Math.min(actual + 1, total - 1))}>
                <ChevronRight size={14} />
              </button>
              <button type="button" aria-label="Al final" onClick={() => onFotograma(e.id, total - 1)}>
                <SkipForward size={14} />
              </button>
              <input
                type="range"
                min={0}
                max={Math.max(total - 1, 0)}
                value={actual}
                onChange={(ev) => onFotograma(e.id, Number(ev.target.value))}
                aria-label="Fotograma"
              />
            </div>
            {e.tipo === "grafo" && (
              <div className="estudio-claves">
                <span><i style={{ background: COLORES_ALGORITMO.actual }} />actual</span>
                <span><i style={{ background: COLORES_ALGORITMO.frontera }} />frontera</span>
                <span><i style={{ background: COLORES_ALGORITMO.visitado }} />visitado</span>
                <span><i style={{ background: COLORES_ALGORITMO.camino }} />camino</span>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

export function Simulaciones({
  enMarcha,
  onAlternar,
  onReiniciar,
}: {
  enMarcha: boolean;
  onAlternar: () => void;
  onReiniciar: () => void;
}) {
  return (
    <div className="estudio-hud estudio-simulaciones">
      <button type="button" onClick={onAlternar} aria-label={enMarcha ? "Pausar simulación" : "Reanudar simulación"}>
        {enMarcha ? <Pause size={14} /> : <Play size={14} />}
      </button>
      <button type="button" onClick={onReiniciar} aria-label="Reiniciar simulación">
        <RotateCcw size={14} />
      </button>
    </div>
  );
}

function PreguntaCard({ paso }: { paso: Paso }) {
  const [elegida, setElegida] = useState<number | null>(null);
  const pregunta = paso.pregunta;
  if (!pregunta) return null;
  const respondida = elegida !== null;
  return (
    <div className="estudio-pregunta">
      <p className="estudio-pregunta-enunciado">{pregunta.enunciado}</p>
      <div className="estudio-pregunta-opciones">
        {pregunta.opciones.map((opcion, i) => {
          const estado = !respondida
            ? ""
            : i === pregunta.correcta
              ? " es-correcta"
              : i === elegida
                ? " es-incorrecta"
                : " es-apagada";
          return (
            <button key={i} type="button" className={`estudio-opcion${estado}`} disabled={respondida} onClick={() => setElegida(i)}>
              {opcion}
            </button>
          );
        })}
      </div>
      {respondida && (
        <p className="estudio-pregunta-explicacion">
          <b>{elegida === pregunta.correcta ? "¡Bien visto!" : "No exactamente."}</b>{" "}
          {pregunta.explicacion}
        </p>
      )}
    </div>
  );
}

export function Pasos({
  escena,
  indice,
  onIr,
}: {
  escena: Escena;
  indice: number;
  onIr: (indice: number) => void;
}) {
  const total = escena.pasos.length;
  if (!total) return null;
  const actual = Math.min(Math.max(indice, 0), total - 1);
  const paso = escena.pasos[actual];
  return (
    <section className="estudio-pasos" aria-label="Explicación por pasos">
      <div className="estudio-pasos-barra">
        <button type="button" disabled={actual === 0} onClick={() => onIr(actual - 1)} aria-label="Paso anterior">
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
                onClick={() => onIr(i)}
              />
            </li>
          ))}
        </ol>
        <span className="estudio-pasos-cuenta">
          Paso {actual + 1} de {total}
        </span>
        <button type="button" disabled={actual === total - 1} onClick={() => onIr(actual + 1)} aria-label="Paso siguiente">
          <ChevronRight size={16} />
        </button>
      </div>
      <p className="estudio-pasos-texto">{paso.texto}</p>
      <PreguntaCard key={`${escena.version}-${actual}`} paso={paso} />
    </section>
  );
}

/** Las lecturas en vivo de las simulaciones, recogidas unas veces por segundo. */
export function Lecturas() {
  const [lista, setLista] = useState(leerLecturas);
  useEffect(() => {
    const reloj = window.setInterval(() => setLista(leerLecturas()), 120);
    return () => window.clearInterval(reloj);
  }, []);
  if (!lista.length) return null;
  return (
    <div className="estudio-lecturas">
      {lista.map(({ id, titulo, filas }) => (
        <section key={id} className="estudio-hud estudio-lectura" aria-label={`Lecturas de ${titulo}`}>
          <h3>{titulo}</h3>
          {filas.map(([k, v]) => (
            <p key={k}>
              <span>{k}</span>
              <b>{v}</b>
            </p>
          ))}
        </section>
      ))}
    </div>
  );
}
