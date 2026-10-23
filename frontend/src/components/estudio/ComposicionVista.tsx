import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { crearIntegrador, type Integrador } from "../../lib/estudio/dinamica";
import { formatear } from "../../lib/estudio/ejes";
import { evaluar } from "../../lib/estudio/expr";
import { publicarLectura, quitarLectura } from "../../lib/estudio/lecturas";
import type { Objeto, Sistema } from "../../lib/estudio/tipos";
import { useAtenuado, useEstudio } from "./contexto";

/**
 * Lo general: objetos cuyas propiedades son fórmulas y sistemas de ecuaciones
 * que se integran en vivo. Nada aquí sabe qué representa la escena.
 */

/** El reloj y los integradores. Va el primero del lienzo: sus valores son
 *  los que leen los objetos en el mismo fotograma. */
export function Motor({ sistemas }: { sistemas: Sistema[] }) {
  const { valores, enMarcha, reinicio, vivo } = useEstudio();
  const integradores = useRef<Map<string, Integrador>>(new Map());
  const firma = JSON.stringify(sistemas.map((s) => [s.id, s.orden, s.iniciales, s.ecuaciones]));
  const valoresRef = useRef(valores);
  valoresRef.current = valores;

  useEffect(() => {
    vivo.current = { t: 0, vars: {} };
    const mapa = new Map<string, Integrador>();
    for (const sistema of sistemas) {
      try {
        mapa.set(sistema.id, crearIntegrador(sistema, valoresRef.current));
      } catch {
        // Una ecuación que mathjs no compila no debería llegar (el servidor
        // la validó); si llega, ese sistema se queda quieto y el resto sigue.
      }
    }
    integradores.current = mapa;
    for (const integrador of mapa.values()) Object.assign(vivo.current.vars, integrador.variables());
    const ids = sistemas.map((s) => s.id);
    return () => ids.forEach((id) => quitarLectura(id));
    // La firma resume `sistemas`: no se reinicia por un objeto nuevo.
  }, [firma, reinicio, vivo]);

  useFrame((_, delta) => {
    if (!enMarcha) return;
    const paso = Math.min(delta, 0.1);
    vivo.current.t += paso;
    for (const sistema of sistemas) {
      const integrador = integradores.current.get(sistema.id);
      if (!integrador) continue;
      Object.assign(vivo.current.vars, integrador.avanzar(paso, { ...valoresRef.current, ...vivo.current.vars }));
      publicarLectura(sistema.id, sistema.etiqueta, [
        ["t", `${integrador.t.toFixed(1)} s`],
        ...sistema.orden.map((v, i): [string, string] => [v, formatear(integrador.estado[i])]),
        ...(integrador.roto ? ([["estado", "diverge: parado"]] as [string, string][]) : []),
      ]);
    }
  });
  return null;
}

function vector(lista: string[] | undefined, scope: Record<string, number>, defecto = 0): number[] {
  return (lista ?? []).map((c) => {
    const v = evaluar(c, scope);
    return Number.isFinite(v) ? v : defecto;
  });
}

const GEOMETRIAS = {
  esfera: new THREE.SphereGeometry(1, 40, 28),
  caja: new THREE.BoxGeometry(1, 1, 1),
  cilindro: new THREE.CylinderGeometry(1, 1, 1, 40),
  cono: new THREE.ConeGeometry(1, 1, 40),
  plano: new THREE.PlaneGeometry(1, 1),
};

/** Cómo el `tamano` de cada forma se convierte en escala de su geometría unidad. */
function escalaDeTamano(forma: Objeto["forma"], t: number[]): [number, number, number] {
  switch (forma) {
    case "esfera":
      return [t[0], t[0], t[0]];
    case "caja":
      return [t[0], t[1], t[2]];
    case "cilindro":
    case "cono":
      return [t[0], t[1], t[0]];
    case "plano":
      return [t[0], t[1], 1];
    default:
      return [1, 1, 1];
  }
}

function Estela({ fuente, longitud, color }: { fuente: React.RefObject<THREE.Object3D | null>; longitud: number; color: string }) {
  const { scene } = useThree();
  const { enMarcha, reinicio } = useEstudio();
  const linea = useMemo(() => {
    const geometria = new THREE.BufferGeometry();
    geometria.setAttribute("position", new THREE.BufferAttribute(new Float32Array(longitud * 3), 3));
    geometria.setDrawRange(0, 0);
    return new THREE.Line(geometria, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.75 }));
  }, [longitud, color]);
  const cuenta = useRef(0);
  useEffect(() => {
    scene.add(linea);
    return () => {
      scene.remove(linea);
    };
  }, [scene, linea]);
  useEffect(() => {
    cuenta.current = 0;
    linea.geometry.setDrawRange(0, 0);
  }, [reinicio, linea]);
  const punto = useMemo(() => new THREE.Vector3(), []);
  useFrame(() => {
    if (!enMarcha || !fuente.current) return;
    fuente.current.getWorldPosition(punto);
    const posiciones = linea.geometry.attributes.position as THREE.BufferAttribute;
    if (cuenta.current < longitud) {
      posiciones.setXYZ(cuenta.current, punto.x, punto.y, punto.z);
      cuenta.current += 1;
    } else {
      // Ventana deslizante: se corre todo un hueco y entra el punto nuevo.
      posiciones.array.copyWithin(0, 3);
      posiciones.setXYZ(longitud - 1, punto.x, punto.y, punto.z);
    }
    posiciones.needsUpdate = true;
    linea.geometry.setDrawRange(0, cuenta.current);
  });
  return null;
}

export function ObjetoVista({ elemento, hijos }: { elemento: Objeto; hijos: Map<string, Objeto[]> }) {
  const { valores, vivo } = useEstudio();
  const { resaltado, atenuado } = useAtenuado(elemento.id);
  const nodo = useRef<THREE.Group>(null);
  const cuerpo = useRef<THREE.Object3D>(null);
  const flecha = useRef<THREE.Group>(null);

  // Lo que no se anima por fotograma (tubos y toros) se construye cuando
  // cambian los deslizadores, con el estado de ese momento.
  const geometria = useMemo(() => {
    const scope = { ...valores, t: vivo.current.t, ...vivo.current.vars };
    const t = vector(elemento.tamano, scope, 1);
    if (elemento.forma === "toro") return new THREE.TorusGeometry(t[0], t[1], 24, 96);
    if (elemento.forma === "tubo" && elemento.puntos && elemento.puntos.length > 1) {
      const puntos = elemento.puntos.map((p) => new THREE.Vector3(...vector(p, scope)));
      const curva = new THREE.CatmullRomCurve3(puntos);
      return new THREE.TubeGeometry(curva, Math.min(puntos.length * 8, 800), t[0], 12, false);
    }
    if (elemento.forma in GEOMETRIAS) return GEOMETRIAS[elemento.forma as keyof typeof GEOMETRIAS];
    return null;
  }, [elemento, valores, vivo]);

  useFrame(() => {
    const scope = { ...valores, t: vivo.current.t, ...vivo.current.vars };
    if (nodo.current) {
      const [x, y, z] = vector(elemento.posicion, scope);
      const [rx, ry, rz] = vector(elemento.rotacion, scope).map((g) => (g * Math.PI) / 180);
      const [sx, sy, sz] = vector(elemento.escala, scope, 1);
      nodo.current.position.set(x, y, z);
      nodo.current.rotation.set(rx, ry, rz);
      nodo.current.scale.set(sx || 1e-6, sy || 1e-6, sz || 1e-6);
    }
    if (cuerpo.current && ["esfera", "caja", "cilindro", "cono", "plano"].includes(elemento.forma)) {
      const [a, b, c] = escalaDeTamano(elemento.forma, vector(elemento.tamano, scope, 1));
      cuerpo.current.scale.set(a, b, c);
    }
    if (flecha.current && elemento.direccion) {
      const d = new THREE.Vector3(...vector(elemento.direccion, scope));
      const largo = d.length();
      flecha.current.visible = largo > 1e-6;
      if (largo > 1e-6) {
        flecha.current.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.normalize());
        const grosor = vector(elemento.tamano, scope, 0.06)[0];
        const punta = Math.min(largo * 0.3, grosor * 6);
        const [cuerpoFlecha, cabeza] = flecha.current.children;
        cuerpoFlecha.scale.set(grosor, largo - punta, grosor);
        cuerpoFlecha.position.set(0, (largo - punta) / 2, 0);
        cabeza.scale.set(grosor * 2.6, punta, grosor * 2.6);
        cabeza.position.set(0, largo - punta / 2, 0);
      }
    }
  });

  const material = (
    <meshStandardMaterial
      color={elemento.color}
      emissive={resaltado ? "#ffb020" : elemento.color}
      emissiveIntensity={resaltado ? 0.6 : elemento.brillo}
      transparent={elemento.opacidad < 1 || atenuado}
      opacity={elemento.opacidad * (atenuado ? 0.25 : 1)}
      side={elemento.forma === "plano" ? THREE.DoubleSide : THREE.FrontSide}
      roughness={0.5}
    />
  );

  return (
    <group ref={nodo}>
      {geometria && (
        <mesh ref={cuerpo as React.RefObject<THREE.Mesh>} geometry={geometria}>
          {material}
        </mesh>
      )}
      {elemento.forma === "flecha" && (
        <group ref={flecha}>
          <mesh geometry={GEOMETRIAS.cilindro}>{material}</mesh>
          <mesh geometry={GEOMETRIAS.cono}>{material}</mesh>
        </group>
      )}
      {elemento.forma === "texto" && (
        <Html center distanceFactor={10} zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
          <span
            className="estudio-rotulo es-texto3d"
            style={{ color: elemento.color, fontSize: `${Math.max(Number(elemento.tamano[0]) || 0.4, 0.05) * 40}px` }}
          >
            {elemento.texto}
          </span>
        </Html>
      )}
      {elemento.etiqueta && elemento.forma !== "texto" && !atenuado && (
        <Html center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
          <span
            className="estudio-rotulo es-nombre"
            style={{ color: elemento.color, display: "inline-block", transform: "translateY(-1.5rem)" }}
          >
            {elemento.etiqueta}
          </span>
        </Html>
      )}
      {elemento.estela > 1 && <Estela fuente={nodo} longitud={elemento.estela} color={elemento.color} />}
      {(hijos.get(elemento.id) ?? []).map((hijo) => (
        <ObjetoVista key={hijo.id} elemento={hijo} hijos={hijos} />
      ))}
    </group>
  );
}

/** La evolución temporal de las variables de un sistema, en una ventana móvil. */
export function SerieTemporal({ elemento: sistema }: { elemento: Sistema }) {
  const { vivo, enMarcha, reinicio } = useEstudio();
  const ventana = 15;
  const capacidad = 900;
  const colores = ["#3b82f6", "#f97316", "#22c55e", "#a855f7", "#ec4899", "#14b8a6", "#eab308", "#ef4444"];
  const lineas = useMemo(
    () =>
      sistema.orden.map((_, i) => {
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(capacidad * 3), 3));
        g.setDrawRange(0, 0);
        return new THREE.Line(g, new THREE.LineBasicMaterial({ color: colores[i % colores.length] }));
      }),
    [sistema.orden.join(",")],
  );
  const muestras = useRef<{ t: number; v: number[] }[]>([]);
  const ultimo = useRef(-1);
  const rango = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    muestras.current = [];
    ultimo.current = -1;
  }, [reinicio]);
  useFrame(() => {
    const t = vivo.current.t;
    if (enMarcha && t - ultimo.current >= 1 / 60) {
      ultimo.current = t;
      muestras.current.push({ t, v: sistema.orden.map((v) => vivo.current.vars[v] ?? Number.NaN) });
      if (muestras.current.length > capacidad) muestras.current.shift();
    }
    const lista = muestras.current.filter((m) => m.t >= t - ventana);
    let minimo = Infinity;
    let maximo = -Infinity;
    for (const m of lista) {
      for (const v of m.v) {
        if (Number.isFinite(v)) {
          minimo = Math.min(minimo, v);
          maximo = Math.max(maximo, v);
        }
      }
    }
    if (!Number.isFinite(minimo)) return;
    if (maximo - minimo < 1e-9) {
      maximo += 1;
      minimo -= 1;
    }
    lineas.forEach((linea, i) => {
      const posiciones = linea.geometry.attributes.position as THREE.BufferAttribute;
      lista.forEach((m, j) => {
        const x = -4.5 + ((m.t - (t - ventana)) / ventana) * 9;
        const y = -2.4 + ((m.v[i] - minimo) / (maximo - minimo)) * 4.8;
        posiciones.setXYZ(j, x, Number.isFinite(y) ? y : -2.4, 0);
      });
      posiciones.needsUpdate = true;
      linea.geometry.setDrawRange(0, lista.length);
    });
    if (rango.current) rango.current.textContent = `${formatear(minimo)} … ${formatear(maximo)}`;
  });
  return (
    <group>
      {lineas.map((linea, i) => (
        <primitive key={i} object={linea} />
      ))}
      <mesh position={[0, 0, -0.01]}>
        <planeGeometry args={[9.2, 5]} />
        <meshBasicMaterial color="#120a18" />
      </mesh>
      <Html position={[-4.5, 2.85, 0]} zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
        <span className="estudio-rotulo es-serie">
          {sistema.orden.map((v, i) => (
            <b key={v} style={{ color: colores[i % colores.length] }}>
              {v}
            </b>
          ))}
          <span ref={rango} />
        </span>
      </Html>
      <Html position={[0, -2.85, 0]} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
        <span className="estudio-rotulo es-marca">últimos {ventana} s →</span>
      </Html>
    </group>
  );
}
