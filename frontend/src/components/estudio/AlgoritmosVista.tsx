import { Html, Line } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";

import { formatear } from "../../lib/estudio/ejes";
import type { Grafo, Ordenacion } from "../../lib/estudio/tipos";
import { useAtenuado, useEstudio } from "./contexto";

type V3 = [number, number, number];

export const COLORES_ALGORITMO = {
  base: "#5d4a66",
  actual: "#ff1026",
  visitado: "#93d6b2",
  frontera: "#92c7ff",
  arista: "#ff9b64",
  camino: "#ffd166",
};

export function GrafoVista({ elemento }: { elemento: Grafo }) {
  const { fotogramas } = useEstudio();
  const { atenuado } = useAtenuado(elemento.id);
  const radio = Math.max(
    1,
    ...elemento.nodos.map((n) => Math.hypot(n.posicion[0], n.posicion[1])),
  );
  const escala = 3.3 / radio;
  const posicion = useMemo(
    () =>
      Object.fromEntries(
        elemento.nodos.map((n) => [
          n.id,
          [n.posicion[0] * escala, n.posicion[1] * escala, n.posicion[2] * escala] as V3,
        ]),
      ),
    [elemento.nodos, escala],
  );
  const recorrido = elemento.recorrido;
  const fotograma = recorrido
    ? recorrido.fotogramas[
        Math.min(fotogramas[elemento.id] ?? 0, recorrido.fotogramas.length - 1)
      ]
    : null;
  const visitados = new Set(fotograma?.visitados ?? []);
  const frontera = new Set(fotograma?.frontera ?? []);
  const camino = fotograma?.camino ?? [];
  const enCamino = new Set(
    camino.slice(1).map((v, i) => [camino[i], v].sort().join("\u0000")),
  );
  const opacidad = atenuado ? 0.25 : 1;

  return (
    <group>
      {elemento.aristas.map((arista, i) => {
        const a = posicion[arista.desde];
        const b = posicion[arista.hasta];
        if (!a || !b) return null;
        const clave = [arista.desde, arista.hasta].sort().join("\u0000");
        const activa =
          fotograma?.arista &&
          ((fotograma.arista[0] === arista.desde && fotograma.arista[1] === arista.hasta) ||
            (!elemento.dirigido &&
              fotograma.arista[0] === arista.hasta &&
              fotograma.arista[1] === arista.desde));
        const color = enCamino.has(clave)
          ? COLORES_ALGORITMO.camino
          : activa
            ? COLORES_ALGORITMO.arista
            : "#7a6a80";
        const dir = new THREE.Vector3(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
        const largo = dir.length();
        dir.normalize();
        const fin = new THREE.Vector3(...b).addScaledVector(dir, -0.36);
        const medio: V3 = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
        return (
          <group key={i}>
            <Line
              points={[a, elemento.dirigido ? (fin.toArray() as V3) : b]}
              color={color}
              lineWidth={enCamino.has(clave) || activa ? 4 : 1.6}
              transparent
              opacity={opacidad}
            />
            {elemento.dirigido && largo > 0.8 && (
              <mesh
                position={fin.clone().addScaledVector(dir, 0.06)}
                quaternion={new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir)}
              >
                <coneGeometry args={[0.09, 0.24, 14]} />
                <meshBasicMaterial color={color} transparent opacity={opacidad} />
              </mesh>
            )}
            {arista.peso !== 1 || elemento.aristas.some((x) => x.peso !== 1) ? (
              <Html position={medio} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
                <span className="estudio-rotulo es-peso">{formatear(arista.peso)}</span>
              </Html>
            ) : null}
          </group>
        );
      })}
      {elemento.nodos.map((nodo) => {
        const p = posicion[nodo.id];
        const color =
          fotograma?.actual === nodo.id
            ? COLORES_ALGORITMO.actual
            : camino.includes(nodo.id)
              ? COLORES_ALGORITMO.camino
              : visitados.has(nodo.id)
                ? COLORES_ALGORITMO.visitado
                : frontera.has(nodo.id)
                  ? COLORES_ALGORITMO.frontera
                  : COLORES_ALGORITMO.base;
        const distancia = fotograma?.distancias?.[nodo.id];
        const textoDistancia = fotograma?.distancias
          ? distancia === null || distancia === undefined
            ? "∞"
            : formatear(distancia)
          : null;
        // Un id corto («A») cabe dentro de la esfera; un nombre («Venas
        // cavas») va debajo, en una pastilla legible.
        const corto = nodo.etiqueta.length <= 3;
        return (
          <group key={nodo.id} position={p}>
            <mesh>
              <sphereGeometry args={[0.3, 28, 28]} />
              <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.35} transparent opacity={opacidad} />
            </mesh>
            {corto ? (
              <Html center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
                <span className="estudio-rotulo es-nodo">
                  {nodo.etiqueta}
                  {textoDistancia && <small>{textoDistancia}</small>}
                </span>
              </Html>
            ) : (
              <Html position={[0, -0.58, 0]} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
                <span className="estudio-rotulo es-nodo-largo" style={{ borderColor: color }}>
                  {nodo.etiqueta}
                  {textoDistancia && <small> · {textoDistancia}</small>}
                </span>
              </Html>
            )}
          </group>
        );
      })}
    </group>
  );
}

export function OrdenacionVista({ elemento }: { elemento: Ordenacion }) {
  const { fotogramas } = useEstudio();
  const { atenuado } = useAtenuado(elemento.id);
  const fotograma =
    elemento.fotogramas[
      Math.min(fotogramas[elemento.id] ?? 0, elemento.fotogramas.length - 1)
    ];
  const valores = fotograma.valores;
  const n = valores.length;
  const maximo = Math.max(...valores.map(Math.abs), 1e-9);
  const ancho = 9 / n;
  const comparando = new Set(fotograma.comparando);
  const escribiendo = new Set(fotograma.escribiendo);
  const ordenados = new Set(fotograma.ordenados);
  const opacidad = atenuado ? 0.25 : 1;

  return (
    <group>
      {valores.map((valor, i) => {
        const alto = Math.max((Math.abs(valor) / maximo) * 5, 0.05);
        const color = escribiendo.has(i)
          ? COLORES_ALGORITMO.actual
          : comparando.has(i)
            ? COLORES_ALGORITMO.arista
            : fotograma.pivote === i
              ? COLORES_ALGORITMO.frontera
              : ordenados.has(i)
                ? COLORES_ALGORITMO.visitado
                : elemento.color;
        const x = -4.5 + ancho * (i + 0.5);
        return (
          <group key={i}>
            <mesh position={[x, -2.6 + alto / 2, 0]}>
              <boxGeometry args={[ancho * 0.78, alto, ancho * 0.78]} />
              <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.25} transparent opacity={opacidad} />
            </mesh>
            {n <= 24 && (
              <Html position={[x, -2.6 + alto + 0.25, 0]} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
                <span className="estudio-rotulo es-marca">{formatear(valor)}</span>
              </Html>
            )}
          </group>
        );
      })}
    </group>
  );
}
