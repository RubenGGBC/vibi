import { Html, Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { formatear } from "../../lib/estudio/ejes";
import {
  avanzar,
  muelle,
  onda,
  pendulo,
  periodoPendulo,
  proyectil,
} from "../../lib/estudio/fisica";
import type { Parametro, Simulacion } from "../../lib/estudio/tipos";
import { publicarLectura, quitarLectura, type Filas } from "../../lib/estudio/lecturas";
import { resolverNumero } from "../../lib/estudio/visibilidad";
import { useAtenuado, useEstudio } from "./contexto";

type V3 = [number, number, number];

/** El valor de un parámetro y, si lo controla un deslizador, su máximo. */
function useParametros(elemento: Simulacion) {
  const { valores, parametros } = useEstudio();
  const valor = (nombre: string) => resolverNumero(elemento.parametros[nombre], valores);
  const maximo = (nombre: string) => {
    const crudo = elemento.parametros[nombre];
    return typeof crudo === "string" ? parametros[crudo]?.maximo ?? valor(nombre) : valor(nombre);
  };
  const extremos = (nombre: string): number[] => {
    const crudo = elemento.parametros[nombre];
    const p: Parametro | undefined = typeof crudo === "string" ? parametros[crudo] : undefined;
    return p ? [p.minimo, p.maximo] : [valor(nombre)];
  };
  return { valor, maximo, extremos };
}

/** Las lecturas de esta simulación van al panel del escenario. */
function usePublicar(elemento: Simulacion) {
  useEffect(() => () => quitarLectura(elemento.id), [elemento.id]);
  return (filas: Filas) => publicarLectura(elemento.id, elemento.etiqueta, filas);
}

function linea(puntos: number, color: string, opacidad = 1): THREE.Line {
  const geometria = new THREE.BufferGeometry();
  geometria.setAttribute("position", new THREE.BufferAttribute(new Float32Array(puntos * 3), 3));
  return new THREE.Line(
    geometria,
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: opacidad }),
  );
}

function Pendulo({ elemento }: { elemento: Simulacion }) {
  const publicar = usePublicar(elemento);
  const { enMarcha, reinicio } = useEstudio();
  const { atenuado } = useAtenuado(elemento.id);
  const { valor, maximo } = useParametros(elemento);
  const L = valor("longitud");
  const g = valor("gravedad");
  const theta0 = valor("angulo_inicial");
  const c = valor("amortiguamiento");
  const escala = 4.2 / maximo("longitud");
  const brazo = useRef<THREE.Group>(null);
  const estado = useRef<number[]>([0, 0]);
  const tiempo = useRef(0);
  const cruces = useRef<number[]>([]);
  const teorico = periodoPendulo(L, g, theta0);

  useEffect(() => {
    estado.current = [(theta0 * Math.PI) / 180, 0];
    tiempo.current = 0;
    cruces.current = [];
  }, [L, g, theta0, c, reinicio]);

  useFrame((_, delta) => {
    if (enMarcha) {
      const antes = estado.current[0];
      estado.current = avanzar(estado.current, pendulo(L, g, c), delta);
      tiempo.current += delta;
      // Cruce por la vertical de izquierda a derecha: un periodo completo.
      if (antes < 0 && estado.current[0] >= 0) cruces.current.push(tiempo.current);
    }
    if (brazo.current) brazo.current.rotation.z = estado.current[0];
    const medidos = cruces.current;
    publicar([
      ["t", `${tiempo.current.toFixed(1)} s`],
      ["θ", `${((estado.current[0] * 180) / Math.PI).toFixed(1)}°`],
      ["T medido", medidos.length > 1 ? `${(medidos.at(-1)! - medidos.at(-2)!).toFixed(3)} s` : "…"],
      ["T teórico", `${teorico.toFixed(3)} s`],
      ["T pequeñas osc.", `${(2 * Math.PI * Math.sqrt(L / g)).toFixed(3)} s`],
    ]);
  });

  const largo = L * escala;
  const opacidad = atenuado ? 0.25 : 1;
  return (
    <group position={[0, 2.6, 0]}>
      <mesh>
        <boxGeometry args={[1.6, 0.08, 0.3]} />
        <meshStandardMaterial color="#5a4a60" />
      </mesh>
      <Line points={[[0, 0, 0], [0, -largo - 0.4, 0]]} color="#6f6573" lineWidth={1} dashed dashSize={0.12} gapSize={0.1} />
      <group ref={brazo}>
        <Line points={[[0, 0, 0], [0, -largo, 0]]} color="#d9cfd4" lineWidth={2} transparent opacity={opacidad} />
        <mesh position={[0, -largo, 0]}>
          <sphereGeometry args={[0.24, 32, 32]} />
          <meshStandardMaterial color={elemento.color} emissive={elemento.color} emissiveIntensity={0.35} transparent opacity={opacidad} />
        </mesh>
      </group>
    </group>
  );
}

function Muelle({ elemento }: { elemento: Simulacion }) {
  const publicar = usePublicar(elemento);
  const { enMarcha, reinicio } = useEstudio();
  const { valor, maximo } = useParametros(elemento);
  const m = valor("masa");
  const k = valor("rigidez");
  const c = valor("amortiguamiento");
  const A = valor("amplitud");
  const escala = 2.4 / maximo("amplitud");
  const pared = -3.8;
  const espiras = 14;
  const resorte = useMemo(() => linea(espiras * 2 + 2, "#d9cfd4"), []);
  const masaRef = useRef<THREE.Mesh>(null);
  const estado = useRef<number[]>([A, 0]);
  const tiempo = useRef(0);

  useEffect(() => {
    estado.current = [A, 0];
    tiempo.current = 0;
  }, [m, k, c, A, reinicio]);

  useFrame((_, delta) => {
    if (enMarcha) {
      estado.current = avanzar(estado.current, muelle(m, k, c), delta);
      tiempo.current += delta;
    }
    const x = estado.current[0] * escala;
    const extremo = x - 0.5;
    if (masaRef.current) masaRef.current.position.x = x;
    const posiciones = resorte.geometry.attributes.position as THREE.BufferAttribute;
    const total = espiras * 2 + 2;
    for (let i = 0; i < total; i += 1) {
      const u = i / (total - 1);
      const zig = i === 0 || i === total - 1 ? 0 : i % 2 === 0 ? 0.28 : -0.28;
      posiciones.setXYZ(i, pared + (extremo - pared) * u, zig, 0);
    }
    posiciones.needsUpdate = true;
    const energia = 0.5 * k * estado.current[0] ** 2 + 0.5 * m * estado.current[1] ** 2;
    publicar([
      ["t", `${tiempo.current.toFixed(1)} s`],
      ["x", `${estado.current[0].toFixed(3)} m`],
      ["v", `${estado.current[1].toFixed(3)} m/s`],
      ["E", `${energia.toFixed(3)} J`],
      ["T", `${(2 * Math.PI * Math.sqrt(m / k)).toFixed(3)} s`],
    ]);
  });

  return (
    <group>
      <mesh position={[pared - 0.1, 0, 0]}>
        <boxGeometry args={[0.2, 1.6, 0.6]} />
        <meshStandardMaterial color="#5a4a60" />
      </mesh>
      <Line points={[[pared, -0.55, 0], [4, -0.55, 0]]} color="#3a2b40" lineWidth={1.5} />
      <Line points={[[0, -0.8, 0], [0, 0.8, 0]]} color="#6f6573" lineWidth={1} dashed dashSize={0.1} gapSize={0.08} />
      <primitive object={resorte} />
      <mesh ref={masaRef} position={[A * escala, 0, 0]}>
        <boxGeometry args={[1, 1, 0.6]} />
        <meshStandardMaterial color={elemento.color} emissive={elemento.color} emissiveIntensity={0.3} />
      </mesh>
    </group>
  );
}

function Proyectil({ elemento }: { elemento: Simulacion }) {
  const publicar = usePublicar(elemento);
  const { enMarcha, reinicio } = useEstudio();
  const { valor, extremos } = useParametros(elemento);
  const v = valor("velocidad");
  const angulo = valor("angulo");
  const g = valor("gravedad");
  const h0 = valor("altura_inicial");
  const tiro = useMemo(() => proyectil(v, angulo, g, h0), [v, angulo, g, h0]);

  // Escala fija para todo lo que permiten los deslizadores: así, al mover el
  // ángulo, el alumno ve que el tiro llega más o menos lejos, no un dibujo que
  // se reencuadra siempre igual.
  const escala = useMemo(() => {
    let alcance = 1e-6;
    let altura = 1e-6;
    for (const vv of extremos("velocidad")) {
      for (const gg of extremos("gravedad")) {
        for (const hh of extremos("altura_inicial")) {
          for (const aa of [...extremos("angulo"), 45]) {
            const t = proyectil(vv, aa, gg, hh);
            alcance = Math.max(alcance, t.alcance);
            altura = Math.max(altura, t.alturaMaxima);
          }
        }
      }
    }
    return Math.min(7.6 / alcance, 4.6 / altura);
  }, [JSON.stringify(elemento.parametros)]);

  const origen: V3 = [-3.8, -2.4, 0];
  const camino = useMemo(() => {
    const puntos: V3[] = [];
    for (let i = 0; i <= 80; i += 1) {
      const [x, y] = tiro.posicion((tiro.tiempo * i) / 80);
      puntos.push([origen[0] + x * escala, origen[1] + y * escala, 0]);
    }
    return puntos;
  }, [tiro, escala]);
  const bola = useRef<THREE.Mesh>(null);
  const t = useRef(0);

  useEffect(() => {
    t.current = 0;
  }, [tiro, reinicio]);

  useFrame((_, delta) => {
    if (enMarcha) {
      t.current += delta;
      if (t.current > tiro.tiempo + 1) t.current = 0;
    }
    const tt = Math.min(t.current, tiro.tiempo);
    const [x, y] = tiro.posicion(tt);
    bola.current?.position.set(origen[0] + x * escala, origen[1] + y * escala, 0);
    publicar([
      ["t", `${tt.toFixed(2)} s`],
      ["x", `${x.toFixed(2)} m`],
      ["y", `${y.toFixed(2)} m`],
      ["alcance", `${formatear(tiro.alcance)} m`],
      ["altura máx.", `${formatear(tiro.alturaMaxima)} m`],
      ["vuelo", `${tiro.tiempo.toFixed(2)} s`],
    ]);
  });

  return (
    <group>
      <Line points={[[origen[0] - 0.3, origen[1], 0], [origen[0] + 8, origen[1], 0]]} color="#5a4a60" lineWidth={2} />
      {h0 > 0 && (
        <mesh position={[origen[0], origen[1] + (h0 * escala) / 2, 0]}>
          <boxGeometry args={[0.3, h0 * escala, 0.3]} />
          <meshStandardMaterial color="#3a2b40" />
        </mesh>
      )}
      <Line points={camino} color={elemento.color} lineWidth={1.5} dashed dashSize={0.15} gapSize={0.1} transparent opacity={0.6} />
      <mesh ref={bola}>
        <sphereGeometry args={[0.16, 24, 24]} />
        <meshStandardMaterial color={elemento.color} emissive={elemento.color} emissiveIntensity={0.5} />
      </mesh>
    </group>
  );
}

function Onda({ elemento }: { elemento: Simulacion }) {
  const publicar = usePublicar(elemento);
  const { enMarcha, reinicio } = useEstudio();
  const { valor, maximo } = useParametros(elemento);
  const A = valor("amplitud");
  const lambda = valor("longitud_onda");
  const f = valor("frecuencia");
  const ventana = 2.5 * maximo("longitud_onda");
  const escalaX = 8 / ventana;
  const escalaY = 1.8 / maximo("amplitud");
  const puntos = 200;
  const cuerda = useMemo(() => linea(puntos, elemento.color), [elemento.color]);
  const marcada = useRef<THREE.Mesh>(null);
  const t = useRef(0);
  const y = useMemo(() => onda(A, lambda, f), [A, lambda, f]);

  useEffect(() => {
    t.current = 0;
  }, [reinicio]);

  useFrame((_, delta) => {
    if (enMarcha) t.current += delta;
    const posiciones = cuerda.geometry.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < puntos; i += 1) {
      const x = (ventana * i) / (puntos - 1);
      posiciones.setXYZ(i, -4 + x * escalaX, y(x, t.current) * escalaY, 0);
    }
    posiciones.needsUpdate = true;
    const xm = ventana / 3;
    marcada.current?.position.set(-4 + xm * escalaX, y(xm, t.current) * escalaY, 0);
    publicar([
      ["t", `${t.current.toFixed(1)} s`],
      ["v = λ·f", `${formatear(lambda * f)} m/s`],
      ["T = 1/f", `${formatear(1 / f)} s`],
    ]);
  });

  return (
    <group>
      <Line points={[[-4.2, 0, 0], [4.2, 0, 0]]} color="#3a2b40" lineWidth={1} />
      <primitive object={cuerda} />
      <mesh ref={marcada}>
        <sphereGeometry args={[0.13, 20, 20]} />
        <meshStandardMaterial color="#ff1026" emissive="#ff1026" emissiveIntensity={0.6} />
      </mesh>
    </group>
  );
}

export function SimulacionVista({ elemento }: { elemento: Simulacion }) {
  const contenido = {
    pendulo: <Pendulo elemento={elemento} />,
    muelle: <Muelle elemento={elemento} />,
    proyectil: <Proyectil elemento={elemento} />,
    onda: <Onda elemento={elemento} />,
  }[elemento.modelo];
  return (
    <group>
      {contenido}
      <Html position={[0, -3.3, 0]} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
        <span className="estudio-rotulo es-ecuacion">{elemento.ecuacion}</span>
      </Html>
    </group>
  );
}
