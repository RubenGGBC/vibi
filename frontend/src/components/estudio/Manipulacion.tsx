import { TransformControls } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import {
  Boxes,
  Eye,
  EyeOff,
  Focus,
  MousePointer2,
  Move3d,
  Rotate3d,
  Scaling,
  Scissors,
  Undo2,
  X,
} from "lucide-react";
import { useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";

import { evaluar } from "../../lib/estudio/expr";
import {
  articulacionesDe,
  clave,
  claveArticulacion,
  colocableAMano,
  enTopes,
  recorrido,
  type EjeDeCorte,
  type Herramienta,
  type Seleccion,
  type Vista3D,
} from "../../lib/estudio/manipulacion";
import type { Objeto } from "../../lib/estudio/tipos";
import { useEstudio, type Transformacion } from "./contexto";

/** ¿Se puede mover lo elegido con el gizmo? Si no, por qué. */
export function motivoDeBloqueo(seleccion: Seleccion | null, objetos: Objeto[]): string | null {
  if (!seleccion) return null;
  const objeto = objetos.find((o) => o.id === seleccion.id);
  if (!objeto) return null;
  if (seleccion.parte) return null;
  return colocableAMano(objeto)
    ? null
    : "Se mueve con fórmulas (tiempo, deslizadores o un sistema): pídele a Vibi que lo cambie";
}

const MODOS = { mover: "translate", girar: "rotate", escalar: "scale" } as const;

/**
 * El gizmo, colgado del nodo de lo elegido. Al soltarlo se lee la
 * transformación propia del nodo (sin la explosión ni los giros animados) y
 * se manda al servidor.
 */
export function Manipulador({
  bloqueado,
  onSoltar,
}: {
  bloqueado: boolean;
  onSoltar: (seleccion: Seleccion, transformacion: Transformacion) => void;
}) {
  const { manipulacion: m } = useEstudio();
  const [nodo, setNodo] = useState<THREE.Object3D | null>(null);
  // Los nodos se registran al montarse los modelos, que cargan tarde: se
  // busca en cada fotograma hasta que aparece.
  useFrame(() => {
    const buscado = m.seleccion ? m.nodos.current.get(clave(m.seleccion)) ?? null : null;
    if (buscado !== nodo) setNodo(buscado);
  });
  if (!nodo || !m.seleccion || m.herramienta === "elegir" || bloqueado) return null;
  const seleccion = m.seleccion;
  const k = clave(seleccion);
  return (
    <TransformControls
      object={nodo}
      mode={MODOS[m.herramienta]}
      size={0.85}
      onMouseDown={() => {
        m.arrastrando.current = k;
      }}
      onMouseUp={() => {
        const leer = m.lectores.current.get(k);
        m.arrastrando.current = null;
        m.soltado.current = performance.now();
        if (leer) onSoltar(seleccion, leer());
      }}
    />
  );
}

const NORMALES: Record<EjeDeCorte, THREE.Vector3> = {
  x: new THREE.Vector3(1, 0, 0),
  y: new THREE.Vector3(0, 1, 0),
  z: new THREE.Vector3(0, 0, 1),
};

/**
 * Coloca el plano de corte sobre la caja de los objetos: la posición del
 * deslizador va de un extremo a otro de lo que hay, sea cual sea su escala.
 */
export function Cortador({ contenido }: { contenido: React.RefObject<THREE.Group | null> }) {
  const { manipulacion: m } = useEstudio();
  const caja = useMemo(() => new THREE.Box3(), []);
  const cuenta = useRef(0);
  useFrame(() => {
    const corte = m.vista.corte;
    const plano = m.planos[0];
    if (!corte || !plano || !contenido.current) return;
    cuenta.current += 1;
    if (cuenta.current % 6 === 1 || caja.isEmpty()) caja.setFromObject(contenido.current);
    if (caja.isEmpty()) return;
    const minimo = caja.min[corte.eje];
    const maximo = caja.max[corte.eje];
    const donde = minimo + (maximo - minimo) * corte.posicion;
    // three descarta lo que queda en el lado negativo del plano: sin invertir
    // se queda lo que está por debajo de `donde`.
    if (corte.invertir) plano.set(NORMALES[corte.eje], -donde);
    else plano.set(NORMALES[corte.eje].clone().negate(), donde);
  });
  return null;
}

function Boton({
  activo,
  titulo,
  onClick,
  children,
  disabled,
}: {
  activo?: boolean;
  titulo: string;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={activo ? "es-activo" : undefined}
      title={titulo}
      aria-label={titulo}
      aria-pressed={activo}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

const HERRAMIENTAS: { id: Herramienta; titulo: string; icono: ReactNode }[] = [
  { id: "elegir", titulo: "Elegir (Esc)", icono: <MousePointer2 size={15} /> },
  { id: "mover", titulo: "Mover (W)", icono: <Move3d size={15} /> },
  { id: "girar", titulo: "Girar (E)", icono: <Rotate3d size={15} /> },
  { id: "escalar", titulo: "Escalar (R)", icono: <Scaling size={15} /> },
];

/**
 * Los mandos de manipular. `lugar` elige qué se pinta: la barra de arriba
 * (herramientas, explosión y corte) o la tarjeta de lo elegido, que va en la
 * columna de la derecha, bajo la leyenda, para no tapar la escena.
 */
export function BarraManipulacion({
  lugar,
  objetos,
  seleccion,
  herramienta,
  vista,
  bloqueo,
  error,
  hayPartes,
  articulaciones,
  valores,
  onArticulacion,
  onHerramienta,
  onSeleccion,
  onVista,
  onRestablecer,
}: {
  lugar: "barra" | "tarjeta";
  objetos: Objeto[];
  seleccion: Seleccion | null;
  herramienta: Herramienta;
  vista: Vista3D;
  bloqueo: string | null;
  error: string | null;
  hayPartes: boolean;
  /** Lo que el alumno ha fijado en cada articulación (`claveArticulacion`). */
  articulaciones: Record<string, number>;
  /** Los deslizadores de la escena: de ellos sale el valor de cada articulación. */
  valores: Record<string, number>;
  onArticulacion: (clave: string, valor: number | null) => void;
  onHerramienta: (h: Herramienta) => void;
  onSeleccion: (s: Seleccion | null) => void;
  onVista: (v: Vista3D) => void;
  onRestablecer: (s: Seleccion) => void;
}) {
  const objeto = seleccion ? objetos.find((o) => o.id === seleccion.id) : undefined;
  const nombre = objeto ? objeto.etiqueta || objeto.id : "";
  const nombreParte = seleccion?.parte ? objeto?.partes?.[seleccion.parte] ?? seleccion.parte : null;
  const tocado = Boolean(
    objeto &&
      (seleccion?.parte
        ? objeto.ajustes?.[seleccion.parte]?.posicion ||
          objeto.ajustes?.[seleccion.parte]?.rotacion ||
          objeto.ajustes?.[seleccion.parte]?.escala
        : objeto.manual),
  );
  const algoEscondido = vista.ocultos.size > 0 || vista.aislado !== null;
  // Lo que se abre o se desliza: las del objeto entero, o las de la pieza elegida.
  const movibles = objeto
    ? articulacionesDe(objeto)
        .map((articulacion, i) => ({ articulacion, k: claveArticulacion(objeto.id, i) }))
        .filter(
          ({ articulacion }) =>
            (articulacion.minimo !== undefined || articulacion.maximo !== undefined) &&
            (!seleccion?.parte || articulacion.partes.includes(seleccion.parte)),
        )
    : [];
  const corte = vista.corte;

  if (lugar === "tarjeta") {
    if (!seleccion || !objeto) return null;
    return (
      <div className="estudio-hud estudio-manipular estudio-manipular-eleccion" aria-label="Lo elegido">
        <span className="estudio-manipular-nombre" style={{ color: objeto.color }}>
          {nombre}
          {nombreParte && <small> › {nombreParte}</small>}
        </span>
        <Boton
          titulo="Ocultar (H)"
          onClick={() => {
            onVista({ ...vista, ocultos: new Set([...vista.ocultos, clave(seleccion)]) });
            onSeleccion(null);
          }}
        >
          <EyeOff size={14} />
        </Boton>
        {!seleccion.parte && (
          <Boton
            activo={vista.aislado === seleccion.id}
            titulo="Ver solo esto"
            onClick={() => onVista({ ...vista, aislado: vista.aislado === seleccion.id ? null : seleccion.id })}
          >
            <Focus size={14} />
          </Boton>
        )}
        {tocado && (
          <Boton titulo="Volver a como estaba" onClick={() => onRestablecer(seleccion)}>
            <Undo2 size={14} />
          </Boton>
        )}
        <Boton titulo="Soltar (Esc)" onClick={() => onSeleccion(null)}>
          <X size={14} />
        </Boton>
        {(error || (bloqueo && herramienta !== "elegir")) && (
          <p className="estudio-manipular-aviso">{error ?? bloqueo}</p>
        )}
        {movibles.map(({ articulacion, k }) => {
          const [minimo, maximo] = recorrido(articulacion);
          const fijado = articulaciones[k];
          const deFormula = evaluar(articulacion.valor, { ...valores, t: 0 });
          const actual = fijado ?? enTopes(Number.isFinite(deFormula) ? deFormula : minimo, articulacion);
          const nombreArt =
            articulacion.etiqueta ?? articulacion.partes.map((p) => objeto.partes?.[p] ?? p).join(", ");
          return (
            <label key={k} className="estudio-manipular-articulacion">
              <span>{nombreArt}</span>
              <input
                type="range"
                min={minimo}
                max={maximo}
                step={(maximo - minimo) / 200}
                value={actual}
                onChange={(e) => onArticulacion(k, Number(e.target.value))}
                aria-label={nombreArt}
              />
              {fijado !== undefined && (
                <button type="button" title="Que vuelva a moverse sola" onClick={() => onArticulacion(k, null)}>
                  <Undo2 size={12} />
                </button>
              )}
            </label>
          );
        })}
        {!seleccion.parte && objeto.partes && Object.keys(objeto.partes).length > 0 && (
          <p className="estudio-manipular-pista">Otro clic sobre una pieza la elige</p>
        )}
      </div>
    );
  }

  return (
    <div className="estudio-hud estudio-manipular estudio-manipular-barra" aria-label="Manipular objetos">
      {HERRAMIENTAS.map((h) => (
        <Boton key={h.id} activo={herramienta === h.id} titulo={h.titulo} onClick={() => onHerramienta(h.id)}>
          {h.icono}
        </Boton>
      ))}
      <span className="estudio-manipular-separador" />
      {hayPartes && (
        <label className="estudio-manipular-control" title="Vista explosionada: separa las piezas">
          <Boxes size={15} />
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={vista.explosion}
            onChange={(e) => onVista({ ...vista, explosion: Number(e.target.value) })}
            aria-label="Separar piezas"
          />
        </label>
      )}
      <Boton
        activo={Boolean(corte)}
        titulo="Cortar con un plano"
        onClick={() => onVista({ ...vista, corte: corte ? null : { eje: "x", posicion: 0.5, invertir: false } })}
      >
        <Scissors size={15} />
      </Boton>
      {corte && (
        <>
          {(["x", "y", "z"] as const).map((eje) => (
            <Boton
              key={eje}
              activo={corte.eje === eje}
              titulo={`Cortar por el eje ${eje}`}
              onClick={() => onVista({ ...vista, corte: { ...corte, eje } })}
            >
              <b>{eje.toUpperCase()}</b>
            </Boton>
          ))}
          <input
            type="range"
            min={0}
            max={1}
            step={0.005}
            value={corte.posicion}
            onChange={(e) => onVista({ ...vista, corte: { ...corte, posicion: Number(e.target.value) } })}
            aria-label="Posición del corte"
          />
          <Boton
            activo={corte.invertir}
            titulo="Quedarse con el otro lado"
            onClick={() => onVista({ ...vista, corte: { ...corte, invertir: !corte.invertir } })}
          >
            <b>⇄</b>
          </Boton>
        </>
      )}
      {algoEscondido && (
        <Boton titulo="Mostrar todo" onClick={() => onVista({ ...vista, ocultos: new Set(), aislado: null })}>
          <Eye size={15} />
        </Boton>
      )}
    </div>
  );
}
