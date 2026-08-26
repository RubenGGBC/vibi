import { useQuery } from "@tanstack/react-query";

import {
  desdeCuando,
  fetchNodos,
  fetchOrdenesDeNodo,
  nodosKey,
  ordenarNodos,
  ordenesDeNodoKey,
} from "../lib/nodos";
import type { NodeDevice, NodeOrder } from "../types";

/**
 * La malla.
 *
 * `nodes.py` son casi mil líneas —presencia, capacidades, órdenes, trastienda—
 * y en pantalla era un dato que decía «2 / 4» dentro de la página de Actividad.
 * Aquí se ve qué equipos hay, cuáles están vivos, **qué sabe hacer cada uno** y
 * qué ha corrido en ellos.
 *
 * Las capacidades importan más de lo que parece: un servidor sin escritorio no
 * trae las de interfaz, y saberlo de un vistazo explica por qué una orden fue
 * a parar a un equipo y no a otro.
 */

/** Lo que enseña cada capacidad, en cristiano. */
const NOMBRES: Record<string, string> = {
  "shell.run": "terminal",
  "fs.read": "archivos",
  "fs.write": "archivos",
  "fs.search": "buscar",
  "ui.snapshot": "interfaz",
  "ui.batch": "interfaz",
  "screen.capture": "pantalla",
  "browser.open": "navegador",
  "media.play": "medios",
  "trastienda.abrir": "trastienda",
};

const legible = (capacidad: string) => NOMBRES[capacidad] ?? capacidad;

/** Sin repetir: tres capacidades de archivos son una ficha, no tres. */
function fichasDe(capacidades: string[]): string[] {
  return [...new Set((capacidades ?? []).map(legible))];
}

function OrdenesDelNodo({ nodo }: { nodo: NodeDevice }) {
  const ordenes = useQuery<NodeOrder[]>({
    queryKey: ordenesDeNodoKey(nodo.id),
    queryFn: () => fetchOrdenesDeNodo(nodo.id),
  });

  if (ordenes.isPending) return <p className="equipo-vacio">Leyendo órdenes…</p>;
  if (ordenes.isError) return <p className="equipo-vacio">No se pudieron leer.</p>;

  const lista = (ordenes.data ?? []).slice(0, 5);
  if (!lista.length) return <p className="equipo-vacio">Nada ha corrido aquí todavía.</p>;

  return (
    <ul className="equipo-ordenes">
      {lista.map((orden) => (
        <li key={orden.id}>
          <b>{orden.capability}</b>
          <span className="equipo-estado">{orden.estado}</span>
          {orden.aprobacion === "pendiente" && (
            <span className="equipo-espera">espera tu permiso</span>
          )}
        </li>
      ))}
    </ul>
  );
}

export function EquiposPage() {
  const nodos = useQuery<NodeDevice[]>({ queryKey: nodosKey, queryFn: fetchNodos });
  const lista = ordenarNodos(nodos.data ?? []);

  return (
    <section className="equipos-page" aria-label="Tus equipos">
      <header className="page-header">
        <div>
          <p className="eyebrow">La malla</p>
          <h1>Equipos</h1>
        </div>
      </header>

      {nodos.isPending ? (
        <div className="loading-list" aria-label="Cargando equipos">
          <i />
          <i />
        </div>
      ) : nodos.isError ? (
        <p className="inline-error">No se pudo leer la malla.</p>
      ) : !lista.length ? (
        <div className="empty-list">
          <h2>Ningún equipo vinculado</h2>
          <p>
            Vibi corre en este ordenador. Para alcanzar otro, instala el agente
            de nodo allí y vincúlalo.
          </p>
        </div>
      ) : (
        <ul className="equipos-lista">
          {lista.map((nodo) => (
            <li key={nodo.id} className="equipo" data-online={nodo.conectado}>
              <header>
                <i className="equipo-pulso" aria-hidden />
                <h2>{nodo.nombre}</h2>
                <span className="equipo-plataforma">{nodo.plataforma}</span>
                <span className="equipo-visto">
                  {nodo.conectado ? "conectado" : `visto ${desdeCuando(nodo.last_seen)}`}
                </span>
              </header>

              <div className="equipo-caps">
                {fichasDe(nodo.capacidades).map((cap) => (
                  <span key={cap} className="equipo-cap">
                    {cap}
                  </span>
                ))}
                {/* El terminal se puede apagar por nodo, y es la capacidad que
                    más cambia lo que Vibi puede hacer allí. */}
                {!nodo.shell_habilitado && (
                  <span className="equipo-cap equipo-cap-off">terminal apagado</span>
                )}
              </div>

              <OrdenesDelNodo nodo={nodo} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
