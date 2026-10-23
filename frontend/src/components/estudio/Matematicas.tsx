import { Html, Line } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";

import { evaluar, funcionDe } from "../../lib/estudio/expr";
import { formatear, marcas } from "../../lib/estudio/ejes";
import type { Funcion, Marca, Sucesion, Superficie } from "../../lib/estudio/tipos";
import { useAtenuado, useEstudio } from "./contexto";

type V3 = [number, number, number];

const COLOR_REJILLA = "#3a2b40";
const COLOR_EJE = "#9c919f";

function Rotulo({
  posicion,
  children,
  clase = "",
  color,
}: {
  posicion: V3;
  children: React.ReactNode;
  clase?: string;
  color?: string;
}) {
  return (
    <Html position={posicion} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
      <span className={`estudio-rotulo ${clase}`} style={color ? { color } : undefined}>
        {children}
      </span>
    </Html>
  );
}

export function Ejes() {
  const { mapa } = useEstudio();
  const { ejes, modo } = mapa;
  if (!ejes.visibles) return null;

  if (modo === "2d") {
    const [x0, x1] = ejes.x;
    const [y0, y1] = ejes.y;
    const ejeX = y0 <= 0 && 0 <= y1 ? 0 : y0;
    const ejeY = x0 <= 0 && 0 <= x1 ? 0 : x0;
    const mx = marcas(ejes.x);
    const my = marcas(ejes.y);
    return (
      <group>
        {mx.map((x) => (
          <Line key={`gx${x}`} points={[mapa.punto(x, y0), mapa.punto(x, y1)]} color={COLOR_REJILLA} lineWidth={1} />
        ))}
        {my.map((y) => (
          <Line key={`gy${y}`} points={[mapa.punto(x0, y), mapa.punto(x1, y)]} color={COLOR_REJILLA} lineWidth={1} />
        ))}
        <Line points={[mapa.punto(x0, ejeX), mapa.punto(x1, ejeX)]} color={COLOR_EJE} lineWidth={1.5} />
        <Line points={[mapa.punto(ejeY, y0), mapa.punto(ejeY, y1)]} color={COLOR_EJE} lineWidth={1.5} />
        {mx.map((x) => {
          const [X, Y] = mapa.punto(x, ejeX);
          return (
            <Rotulo key={`tx${x}`} posicion={[X, Y - 0.28, 0]} clase="es-marca">
              {formatear(x)}
            </Rotulo>
          );
        })}
        {my.map((y) => {
          if (y === ejeX) return null;
          const [X, Y] = mapa.punto(ejeY, y);
          return (
            <Rotulo key={`ty${y}`} posicion={[X - 0.35, Y, 0]} clase="es-marca">
              {formatear(y)}
            </Rotulo>
          );
        })}
        <Rotulo posicion={[mapa.ancho / 2 + 0.35, mapa.punto(x1, ejeX)[1], 0]} clase="es-eje">x</Rotulo>
        <Rotulo posicion={[mapa.punto(ejeY, y1)[0], mapa.alto / 2 + 0.3, 0]} clase="es-eje">y</Rotulo>
      </group>
    );
  }

  const [x0, x1] = ejes.x;
  const [y0, y1] = ejes.y;
  const [z0, z1] = ejes.z;
  const zSuelo = z0 <= 0 && 0 <= z1 ? 0 : z0;
  const mx = marcas(ejes.x, 4);
  const my = marcas(ejes.y, 4);
  const mz = marcas(ejes.z, 4);
  const xEje = x0 <= 0 && 0 <= x1 ? 0 : x0;
  const yEje = y0 <= 0 && 0 <= y1 ? 0 : y0;
  return (
    <group>
      {mx.map((x) => (
        <Line key={`gx${x}`} points={[mapa.punto(x, y0, zSuelo), mapa.punto(x, y1, zSuelo)]} color={COLOR_REJILLA} lineWidth={1} />
      ))}
      {my.map((y) => (
        <Line key={`gy${y}`} points={[mapa.punto(x0, y, zSuelo), mapa.punto(x1, y, zSuelo)]} color={COLOR_REJILLA} lineWidth={1} />
      ))}
      <Line points={[mapa.punto(x0, yEje, zSuelo), mapa.punto(x1, yEje, zSuelo)]} color="#ff6b7a" lineWidth={1.6} />
      <Line points={[mapa.punto(xEje, y0, zSuelo), mapa.punto(xEje, y1, zSuelo)]} color="#93d6b2" lineWidth={1.6} />
      <Line points={[mapa.punto(xEje, yEje, z0), mapa.punto(xEje, yEje, z1)]} color="#92c7ff" lineWidth={1.6} />
      <Rotulo posicion={mapa.punto(x1 + (x1 - x0) * 0.06, yEje, zSuelo)} clase="es-eje" color="#ff6b7a">x</Rotulo>
      <Rotulo posicion={mapa.punto(xEje, y1 + (y1 - y0) * 0.06, zSuelo)} clase="es-eje" color="#93d6b2">y</Rotulo>
      <Rotulo posicion={mapa.punto(xEje, yEje, z1 + (z1 - z0) * 0.06)} clase="es-eje" color="#92c7ff">z</Rotulo>
      {mx.map((x) => (
        <Rotulo key={`tx${x}`} posicion={mapa.punto(x, y0 - (y1 - y0) * 0.07, zSuelo)} clase="es-marca">
          {formatear(x)}
        </Rotulo>
      ))}
      {my.map((y) => (
        <Rotulo key={`ty${y}`} posicion={mapa.punto(x1 + (x1 - x0) * 0.07, y, zSuelo)} clase="es-marca">
          {formatear(y)}
        </Rotulo>
      ))}
      {mz.map((z) => (
        <Rotulo key={`tz${z}`} posicion={mapa.punto(xEje - (x1 - x0) * 0.05, yEje, z)} clase="es-marca">
          {formatear(z)}
        </Rotulo>
      ))}
    </group>
  );
}

/** Parte una curva donde deja de existir o se sale de la caja. */
function tramos(puntos: { x: number; v: number }[], mapa: ReturnType<typeof useEstudio>["mapa"]): V3[][] {
  const lista: V3[][] = [];
  let actual: V3[] = [];
  for (const { x, v } of puntos) {
    if (Number.isFinite(v) && mapa.dentro(v)) {
      actual.push(mapa.modo === "3d" ? mapa.punto(x, 0, v) : mapa.punto(x, v));
    } else if (actual.length) {
      lista.push(actual);
      actual = [];
    }
  }
  if (actual.length) lista.push(actual);
  return lista.filter((t) => t.length > 1);
}

export function FuncionVista({ elemento }: { elemento: Funcion }) {
  const { valores, mapa } = useEstudio();
  const { resaltado, atenuado } = useAtenuado(elemento.id);
  const segmentos = useMemo(() => {
    const [a, b] = elemento.dominio ?? mapa.ejes.x;
    const f = funcionDe(elemento.expresion, elemento.variable, valores);
    const n = 600;
    const puntos = Array.from({ length: n }, (_, i) => {
      const x = a + ((b - a) * i) / (n - 1);
      return { x, v: f(x) };
    });
    return tramos(puntos, mapa);
  }, [elemento, valores, mapa]);
  const ultimo = segmentos.at(-1)?.at(-1);
  return (
    <group>
      {segmentos.map((puntos, i) => (
        <Line
          key={i}
          points={puntos}
          color={elemento.color}
          lineWidth={resaltado ? 4.5 : 2.6}
          transparent
          opacity={atenuado ? 0.22 : 1}
        />
      ))}
      {ultimo && !atenuado && (
        <Rotulo posicion={[ultimo[0] + 0.15, ultimo[1] + 0.3, ultimo[2]]} color={elemento.color} clase="es-nombre">
          {elemento.etiqueta}
        </Rotulo>
      )}
    </group>
  );
}

export function terminosDe(
  elemento: Sucesion,
  valores: Record<string, number>,
): { n: number; v: number }[] {
  const hasta =
    typeof elemento.hasta === "number"
      ? elemento.hasta
      : Math.round(valores[elemento.hasta] ?? elemento.desde);
  const f = funcionDe(elemento.expresion, "n", valores);
  const lista: { n: number; v: number }[] = [];
  let suma = 0;
  for (let n = elemento.desde; n <= hasta; n += 1) {
    const termino = f(n);
    suma += termino;
    lista.push({ n, v: elemento.acumulada ? suma : termino });
  }
  return lista;
}

export function SucesionVista({ elemento }: { elemento: Sucesion }) {
  const { valores, mapa } = useEstudio();
  const { resaltado, atenuado } = useAtenuado(elemento.id);
  const terminos = useMemo(() => terminosDe(elemento, valores), [elemento, valores]);
  const opacidad = atenuado ? 0.2 : 1;
  const estilo = elemento.estilo === "barras" && terminos.length > 400 ? "linea" : elemento.estilo;
  const [v0, v1] = mapa.modo === "3d" ? mapa.ejes.z : mapa.ejes.y;
  const base = Math.min(Math.max(0, v0), v1);
  const situar = (n: number, v: number): V3 =>
    mapa.modo === "3d" ? mapa.punto(n, 0, v) : mapa.punto(n, v);
  const visibles = terminos.filter(({ v }) => Number.isFinite(v));
  const ultimo = visibles.at(-1);

  return (
    <group>
      {estilo === "barras" &&
        visibles.map(({ n, v }) => {
          const recortado = Math.min(Math.max(v, v0), v1);
          const [X, Y0] = situar(n, base);
          const Y1 = situar(n, recortado)[1];
          const alto = Math.abs(Y1 - Y0);
          if (alto < 1e-4) return null;
          const ancho = Math.max(Math.min(mapa.unidadX * 0.72, 0.6), 0.02);
          return (
            <mesh key={n} position={[X, (Y0 + Y1) / 2, 0]}>
              <boxGeometry args={[ancho, alto, mapa.modo === "3d" ? ancho : 0.02]} />
              <meshStandardMaterial
                color={elemento.color}
                emissive={elemento.color}
                emissiveIntensity={resaltado ? 0.55 : 0.18}
                transparent
                opacity={opacidad * 0.92}
              />
            </mesh>
          );
        })}
      {estilo === "puntos" &&
        visibles
          .filter(({ v }) => mapa.dentro(v))
          .map(({ n, v }) => (
            <mesh key={n} position={situar(n, v)}>
              <sphereGeometry args={[resaltado ? 0.09 : 0.065, 12, 12]} />
              <meshStandardMaterial color={elemento.color} emissive={elemento.color} emissiveIntensity={0.4} transparent opacity={opacidad} />
            </mesh>
          ))}
      {estilo === "linea" &&
        tramos(terminos.map(({ n, v }) => ({ x: n, v })), mapa).map((puntos, i) => (
          <Line key={i} points={puntos} color={elemento.color} lineWidth={resaltado ? 4 : 2.4} transparent opacity={opacidad} />
        ))}
      {ultimo && !atenuado && mapa.dentro(ultimo.v) && (
        <Rotulo
          posicion={(() => {
            const p = situar(ultimo.n, ultimo.v);
            return [p[0] + 0.2, p[1] + 0.3, p[2]] as V3;
          })()}
          color={elemento.color}
          clase="es-nombre"
        >
          {elemento.etiqueta} · {formatear(ultimo.v)}
        </Rotulo>
      )}
    </group>
  );
}

const RAMPA = ["#2c3e8f", "#6b3fa0", "#c2316b", "#ff6b3d", "#ffd166"].map((c) => new THREE.Color(c));

function colorRampa(t: number, destino: THREE.Color): THREE.Color {
  const u = Math.min(Math.max(t, 0), 1) * (RAMPA.length - 1);
  const i = Math.min(Math.floor(u), RAMPA.length - 2);
  return destino.copy(RAMPA[i]).lerp(RAMPA[i + 1], u - i);
}

export function SuperficieVista({ elemento }: { elemento: Superficie }) {
  const { valores, mapa } = useEstudio();
  const { atenuado } = useAtenuado(elemento.id);
  const geometria = useMemo(() => {
    const [x0, x1] = mapa.ejes.x;
    const [y0, y1] = mapa.ejes.y;
    const [z0, z1] = mapa.ejes.z;
    const n = elemento.resolucion;
    const posiciones = new Float32Array((n + 1) * (n + 1) * 3);
    const colores = new Float32Array((n + 1) * (n + 1) * 3);
    const color = new THREE.Color();
    const scope = { ...valores };
    for (let i = 0; i <= n; i += 1) {
      for (let j = 0; j <= n; j += 1) {
        const x = x0 + ((x1 - x0) * i) / n;
        const y = y0 + ((y1 - y0) * j) / n;
        scope.x = x;
        scope.y = y;
        const z = evaluar(elemento.expresion, scope);
        const valido = Number.isFinite(z);
        const recortado = valido ? Math.min(Math.max(z, z0), z1) : z0;
        const k = (i * (n + 1) + j) * 3;
        posiciones.set(mapa.punto(x, y, recortado), k);
        if (valido) colorRampa((recortado - z0) / (z1 - z0), color);
        else color.set("#1b0d23");
        colores.set([color.r, color.g, color.b], k);
      }
    }
    const indices: number[] = [];
    for (let i = 0; i < n; i += 1) {
      for (let j = 0; j < n; j += 1) {
        const a = i * (n + 1) + j;
        const b = a + n + 1;
        indices.push(a, b, a + 1, b, b + 1, a + 1);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(posiciones, 3));
    g.setAttribute("color", new THREE.BufferAttribute(colores, 3));
    g.setIndex(indices);
    g.computeVertexNormals();
    return g;
  }, [elemento, valores, mapa]);

  return (
    <group>
      <mesh geometry={geometria}>
        <meshStandardMaterial vertexColors side={THREE.DoubleSide} transparent opacity={atenuado ? 0.25 : 0.94} roughness={0.55} />
      </mesh>
      <mesh geometry={geometria}>
        <meshBasicMaterial wireframe color="#fff8f5" transparent opacity={atenuado ? 0.03 : 0.08} />
      </mesh>
    </group>
  );
}

function coordenadas(lista: string[], valores: Record<string, number>): number[] {
  return lista.map((c) => evaluar(c, valores));
}

export function MarcaVista({ elemento }: { elemento: Marca }) {
  const { valores, mapa } = useEstudio();
  const { resaltado, atenuado } = useAtenuado(elemento.id);
  const [x, y, z] = coordenadas(elemento.posicion, valores);
  if (![x, y, z].every(Number.isFinite)) return null;
  const p = mapa.punto(x, y, z);
  const opacidad = atenuado ? 0.25 : 1;

  if (elemento.tipo === "etiqueta") {
    return (
      <Rotulo posicion={p} clase={`es-nota${resaltado ? " es-resaltado" : ""}`}>
        {elemento.etiqueta}
      </Rotulo>
    );
  }
  if (elemento.tipo === "punto") {
    return (
      <group>
        <mesh position={p}>
          <sphereGeometry args={[resaltado ? 0.16 : 0.12, 20, 20]} />
          <meshStandardMaterial color={elemento.color} emissive={elemento.color} emissiveIntensity={0.5} transparent opacity={opacidad} />
        </mesh>
        {elemento.etiqueta && !atenuado && (
          <Rotulo posicion={[p[0] + 0.2, p[1] + 0.3, p[2]]} color={elemento.color} clase="es-nombre">
            {elemento.etiqueta} ({formatear(x)}, {formatear(y)}
            {mapa.modo === "3d" ? `, ${formatear(z)}` : ""})
          </Rotulo>
        )}
      </group>
    );
  }
  const [ox, oy, oz] = coordenadas(elemento.desde ?? ["0", "0", "0"], valores);
  const o = mapa.punto(ox, oy, oz);
  const direccion = new THREE.Vector3(p[0] - o[0], p[1] - o[1], p[2] - o[2]);
  const largo = direccion.length();
  if (largo < 1e-6) return null;
  const punta = Math.min(0.32, largo * 0.35);
  const finCuerpo = new THREE.Vector3(...o).addScaledVector(direccion.clone().normalize(), largo - punta);
  const giro = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), direccion.clone().normalize());
  const centroPunta = new THREE.Vector3(...o).addScaledVector(direccion.clone().normalize(), largo - punta / 2);
  return (
    <group>
      <Line points={[o, finCuerpo.toArray() as V3]} color={elemento.color} lineWidth={resaltado ? 4.5 : 3} transparent opacity={opacidad} />
      <mesh position={centroPunta} quaternion={giro}>
        <coneGeometry args={[punta * 0.42, punta, 18]} />
        <meshStandardMaterial color={elemento.color} emissive={elemento.color} emissiveIntensity={0.4} transparent opacity={opacidad} />
      </mesh>
      {elemento.etiqueta && !atenuado && (
        <Rotulo posicion={[p[0] + 0.2, p[1] + 0.25, p[2]]} color={elemento.color} clase="es-nombre">
          {elemento.etiqueta}
        </Rotulo>
      )}
    </group>
  );
}
