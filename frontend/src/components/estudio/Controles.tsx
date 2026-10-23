import {
  ChevronLeft,
  ChevronRight,
  MessageCircleQuestion,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { aplicarRespuesta, responder } from "../../lib/estudio/api";
import { formatear } from "../../lib/estudio/ejes";
import { leerLecturas } from "../../lib/estudio/lecturas";
import type { Elemento, Escena, Grafo, Ordenacion } from "../../lib/estudio/tipos";
import { elegidasEn, estadoPregunta, mensajeTrasFallar } from "../../lib/estudio/tutor";
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
  // Las piezas anidadas van con su padre, y una escena compuesta de muchos
  // objetos no convierte la leyenda en un inventario.
  const raiz = escena.elementos.filter((e) => !(e.tipo === "objeto" && e.padre));
  const MAXIMO = 7;
  const mostrados = raiz.slice(0, MAXIMO);
  const resto = raiz.length - mostrados.length;
  return (
    <ul className="estudio-hud estudio-leyenda" aria-label="Elementos de la escena">
      {resto > 0 && <li className="estudio-leyenda-mas">y {resto} más</li>}
      {mostrados.map((e) => {
        const origen = ORIGENES[e.procedencia?.origen] ?? ORIGENES.modelo;
        return (
          <li key={e.id} className={visibles.has(e.id) ? "" : "es-oculto"}>
            <i style={{ background: e.color }} />
            <span className="estudio-leyenda-nombre">{e.etiqueta || e.id}</span>
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

export function PreguntaCard({
  escena,
  indice,
  onPedirTutor,
  onDecir,
}: {
  escena: Escena;
  indice: number;
  onPedirTutor: (texto: string) => void;
  onDecir?: (texto: string) => void;
}) {
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const pregunta = escena.pasos[indice].pregunta;
  if (!pregunta) return null;
  const elegidas = elegidasEn(escena, indice);
  const estado = estadoPregunta(pregunta, elegidas);

  const elegir = (opcion: number) => {
    setError(null);
    const tras = estadoPregunta(pregunta, [...elegidas, opcion]);
    if (tras.pista) onDecir?.(`Casi. ${tras.pista}`);
    else if (tras.explicacion) {
      const entrada = tras.acertada ? "¡Eso es!" : `Era ${pregunta.opciones[pregunta.correcta]}.`;
      onDecir?.(`${entrada} ${tras.explicacion}`);
    }
    aplicarRespuesta(client, indice, [...elegidas, opcion]);
    responder(indice, opcion).catch((e: unknown) => {
      aplicarRespuesta(client, indice, elegidas);
      setError(e instanceof Error ? e.message : "No se pudo guardar la respuesta");
    });
  };

  return (
    <div className="estudio-pregunta">
      <p className="estudio-pregunta-enunciado">{pregunta.enunciado}</p>
      <div className="estudio-pregunta-opciones">
        {pregunta.opciones.map((opcion, i) => {
          const probada = elegidas.includes(i);
          const clase = estado.resuelta
            ? i === pregunta.correcta
              ? " es-correcta"
              : probada
                ? " es-incorrecta"
                : " es-apagada"
            : probada
              ? " es-incorrecta"
              : "";
          return (
            <button
              key={i}
              type="button"
              className={`estudio-opcion${clase}`}
              disabled={estado.resuelta || probada}
              onClick={() => elegir(i)}
            >
              {opcion}
            </button>
          );
        })}
      </div>
      {estado.pista && (
        <p className="estudio-pregunta-pista">
          <b>Casi.</b> {estado.pista}
        </p>
      )}
      {estado.explicacion && (
        <p className="estudio-pregunta-explicacion">
          <b>
            {estado.acertada
              ? estado.fallos
                ? "¡Eso es!"
                : "¡Bien visto!"
              : `Era «${pregunta.opciones[pregunta.correcta]}».`}
          </b>{" "}
          {estado.explicacion}
        </p>
      )}
      {estado.resuelta && !estado.acertada && (
        <button
          type="button"
          className="estudio-tutor-boton"
          onClick={() => onPedirTutor(mensajeTrasFallar(escena, indice))}
        >
          <MessageCircleQuestion size={14} /> ¿Por qué? Explícamelo
        </button>
      )}
      {error && <p className="estudio-pregunta-error">{error}</p>}
    </div>
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
