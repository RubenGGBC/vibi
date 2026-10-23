import { Html, useGLTF } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { Suspense, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { apiUrl } from "../../lib/api";
import { getToken } from "../../lib/auth";
import type { ModeloGltf, Molecula } from "../../lib/estudio/tipos";
import { useAtenuado, useEstudio } from "./contexto";

type V3 = [number, number, number];

/** Colores CPK y radios covalentes (Å) de los elementos más comunes. */
const ELEMENTOS: Record<string, { color: string; radio: number }> = {
  H: { color: "#f5f5f5", radio: 0.31 },
  C: { color: "#4a4a4a", radio: 0.76 },
  N: { color: "#3050f8", radio: 0.71 },
  O: { color: "#ff0d0d", radio: 0.66 },
  F: { color: "#90e050", radio: 0.57 },
  P: { color: "#ff8000", radio: 1.07 },
  S: { color: "#ffff30", radio: 1.05 },
  Cl: { color: "#1ff01f", radio: 1.02 },
  Br: { color: "#a62929", radio: 1.2 },
  I: { color: "#940094", radio: 1.39 },
  Na: { color: "#ab5cf2", radio: 1.66 },
  K: { color: "#8f40d4", radio: 2.03 },
  Mg: { color: "#8aff00", radio: 1.41 },
  Ca: { color: "#3dff00", radio: 1.76 },
  Fe: { color: "#e06633", radio: 1.32 },
};
const DESCONOCIDO = { color: "#ff1493", radio: 0.8 };

function Enlace({ a, b, orden, opacidad }: { a: V3; b: V3; orden: number; opacidad: number }) {
  const inicio = new THREE.Vector3(...a);
  const fin = new THREE.Vector3(...b);
  const dir = fin.clone().sub(inicio);
  const largo = dir.length();
  const centro = inicio.clone().add(fin).multiplyScalar(0.5);
  const giro = new THREE.Quaternion().setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    dir.clone().normalize(),
  );
  // Los enlaces dobles y triples se separan en un eje perpendicular cualquiera.
  const lado = new THREE.Vector3(1, 0, 0).applyQuaternion(giro).multiplyScalar(0.11);
  const desplazamientos =
    orden === 2 ? [-0.5, 0.5] : orden === 3 ? [-1, 0, 1] : [0];
  return (
    <group>
      {desplazamientos.map((d) => (
        <mesh key={d} position={centro.clone().addScaledVector(lado, d)} quaternion={giro}>
          <cylinderGeometry args={[orden > 1 ? 0.045 : 0.07, orden > 1 ? 0.045 : 0.07, largo, 12]} />
          <meshStandardMaterial color="#b9b1bd" roughness={0.4} transparent opacity={opacidad} />
        </mesh>
      ))}
    </group>
  );
}

export function MoleculaVista({ elemento }: { elemento: Molecula }) {
  const { enMarcha } = useEstudio();
  const { atenuado } = useAtenuado(elemento.id);
  const [rotulos, setRotulos] = useState(false);
  const giro = useRef<THREE.Group>(null);
  // Gira despacio para que se vea en 3D sin tener que arrastrar; la pausa de
  // las simulaciones también la para.
  useFrame((_, delta) => {
    if (enMarcha && giro.current) giro.current.rotation.y += delta * 0.35;
  });
  const { posiciones, escala } = useMemo(() => {
    const n = elemento.atomos.length || 1;
    const centro = elemento.atomos
      .reduce((acc, a) => acc.add(new THREE.Vector3(...a.posicion)), new THREE.Vector3())
      .divideScalar(n);
    const relativas = elemento.atomos.map(
      (a) => new THREE.Vector3(...a.posicion).sub(centro).toArray() as V3,
    );
    const extension = Math.max(1, ...relativas.map((p) => Math.hypot(...p)));
    return { posiciones: relativas, escala: 3 / extension };
  }, [elemento.atomos]);
  const opacidad = atenuado ? 0.25 : 1;
  const enEscala = (p: V3): V3 => [p[0] * escala, p[1] * escala, p[2] * escala];

  return (
    <group ref={giro} onClick={() => setRotulos((v) => !v)}>
      {elemento.enlaces.map((enlace, i) => (
        <Enlace
          key={i}
          a={enEscala(posiciones[enlace.a])}
          b={enEscala(posiciones[enlace.b])}
          orden={enlace.orden}
          opacidad={opacidad}
        />
      ))}
      {elemento.atomos.map((atomo, i) => {
        const datos = ELEMENTOS[atomo.elemento] ?? DESCONOCIDO;
        return (
          <mesh key={i} position={enEscala(posiciones[i])}>
            <sphereGeometry args={[datos.radio * 0.42 * Math.min(escala, 1.6), 28, 28]} />
            <meshStandardMaterial color={datos.color} roughness={0.35} metalness={0.05} transparent opacity={opacidad} />
            {rotulos && (
              <Html center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
                <span className="estudio-rotulo es-atomo">{atomo.elemento}</span>
              </Html>
            )}
          </mesh>
        );
      })}
    </group>
  );
}

function ModeloCargado({ elemento }: { elemento: ModeloGltf }) {
  const { paso } = useEstudio();
  const { atenuado } = useAtenuado(elemento.id);
  const gltf = useGLTF(apiUrl(elemento.url), false, false, (loader) => {
    const token = getToken();
    if (token) loader.setRequestHeader({ Authorization: `Bearer ${token}` });
  });
  // GLTFLoader limpia los nombres de los nodos («Right atrium» llega como
  // «Right_atrium»), así que el catálogo se compara con la misma limpieza.
  const etiquetaDe = useMemo(
    () =>
      new Map(
        Object.entries(elemento.partes).map(([malla, etiqueta]) => [
          THREE.PropertyBinding.sanitizeNodeName(malla),
          etiqueta,
        ]),
      ),
    [elemento.partes],
  );
  const resaltadas = useMemo(() => {
    // Un nombre puede agrupar varias mallas: «Válvula aórtica» son tres valvas.
    const porEtiqueta = new Map<string, string[]>();
    for (const [malla, etiqueta] of Object.entries(elemento.partes)) {
      const clave = etiqueta.toLocaleLowerCase();
      porEtiqueta.set(clave, [...(porEtiqueta.get(clave) ?? []), malla]);
    }
    const pedidas = [...elemento.resaltadas, ...(paso.partes.get(elemento.id) ?? [])];
    return new Set(
      pedidas
        .flatMap((p) => porEtiqueta.get(p.toLocaleLowerCase()) ?? [p])
        .map((malla) => THREE.PropertyBinding.sanitizeNodeName(malla)),
    );
  }, [elemento, paso]);

  const { escena, rotulos } = useMemo(() => {
    const copia = gltf.scene.clone(true);
    const caja = new THREE.Box3().setFromObject(copia);
    const tamano = caja.getSize(new THREE.Vector3());
    const escala = 6 / Math.max(tamano.x, tamano.y, tamano.z, 1e-6);
    const centro = caja.getCenter(new THREE.Vector3());
    copia.position.sub(centro.multiplyScalar(escala));
    copia.scale.setScalar(escala);
    copia.updateMatrixWorld(true);
    const lista: { texto: string; posicion: V3 }[] = [];
    copia.traverse((objeto) => {
      if (!(objeto instanceof THREE.Mesh)) return;
      const encendida = resaltadas.has(objeto.name);
      const material = (objeto.material as THREE.MeshStandardMaterial).clone();
      material.transparent = true;
      material.opacity = atenuado || (resaltadas.size > 0 && !encendida) ? 0.28 : 1;
      if (encendida) {
        // Ámbar y no rojo: sobre un músculo granate, el rojo no se distingue.
        material.emissive = new THREE.Color("#ffb020");
        material.emissiveIntensity = 0.45;
        const texto = etiquetaDe.get(objeto.name) ?? objeto.name;
        // Una pastilla por nombre, aunque lo compartan varias mallas.
        if (!lista.some((r) => r.texto === texto)) {
          const centroParte = new THREE.Box3().setFromObject(objeto).getCenter(new THREE.Vector3());
          lista.push({ texto, posicion: centroParte.toArray() as V3 });
        }
      }
      objeto.material = material;
    });
    return { escena: copia, rotulos: lista };
  }, [gltf, resaltadas, atenuado, etiquetaDe]);

  return (
    <group>
      <primitive object={escena} />
      {rotulos.map(({ texto, posicion }) => (
        <Html key={texto} position={posicion} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
          <span className="estudio-rotulo es-parte">{texto}</span>
        </Html>
      ))}
    </group>
  );
}

export function ModeloVista({ elemento }: { elemento: ModeloGltf }) {
  return (
    <Suspense
      fallback={
        <Html center>
          <span className="estudio-rotulo es-nota">Cargando {elemento.etiqueta}…</span>
        </Html>
      }
    >
      <ModeloCargado elemento={elemento} />
    </Suspense>
  );
}
