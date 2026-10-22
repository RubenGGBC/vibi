import { Html, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { Component, useEffect, useMemo, useState, type ReactNode } from "react";
import * as THREE from "three";

import { crearMapa } from "../../lib/estudio/ejes";
import type { Elemento, Escena } from "../../lib/estudio/tipos";
import { TIPOS_DE_EJES } from "../../lib/estudio/tipos";
import type { EstadoDePaso } from "../../lib/estudio/visibilidad";
import { GrafoVista, OrdenacionVista } from "./AlgoritmosVista";
import { Contexto, type ContextoEstudio } from "./contexto";
import { Ejes, FuncionVista, MarcaVista, SucesionVista, SuperficieVista } from "./Matematicas";
import { ModeloVista, MoleculaVista } from "./QuimicaVista";
import { SimulacionVista } from "./SimulacionVista";

/** Un elemento roto (un modelo que no carga) no tumba el lienzo entero. */
class Aislado extends Component<{ nombre: string; children: ReactNode }, { error: boolean }> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    if (this.state.error) {
      return (
        <Html center>
          <span className="estudio-rotulo es-nota">No se pudo pintar «{this.props.nombre}»</span>
        </Html>
      );
    }
    return this.props.children;
  }
}

function Vista({ elemento }: { elemento: Elemento }) {
  switch (elemento.tipo) {
    case "funcion":
      return <FuncionVista elemento={elemento} />;
    case "sucesion":
      return <SucesionVista elemento={elemento} />;
    case "superficie":
      return <SuperficieVista elemento={elemento} />;
    case "punto":
    case "vector":
    case "etiqueta":
      return <MarcaVista elemento={elemento} />;
    case "simulacion":
      return <SimulacionVista elemento={elemento} />;
    case "grafo":
      return <GrafoVista elemento={elemento} />;
    case "ordenacion":
      return <OrdenacionVista elemento={elemento} />;
    case "molecula":
      return <MoleculaVista elemento={elemento} />;
    case "modelo":
      return <ModeloVista elemento={elemento} />;
  }
}

interface Bloque {
  clave: string;
  ancho: number;
  alto: number;
  hondo: number;
  elementos: Elemento[];
  ejes: boolean;
}

const SEPARACION = 1.6;

/**
 * Reparte la escena en bloques puestos en fila: uno con los ejes y todo lo
 * que se dibuja sobre ellos, y uno por cada simulación, grafo, ordenación,
 * molécula o modelo. El modelo nunca coloca nada; esto lo hace solo.
 */
export function bloquesDe(escena: Escena, visibles: Set<string>): Bloque[] {
  const enEjes = escena.elementos.filter((e) => TIPOS_DE_EJES.has(e.tipo));
  const sueltos = escena.elementos.filter((e) => !TIPOS_DE_EJES.has(e.tipo));
  const bloques: Bloque[] = [];
  const tresD = escena.modo === "3d";
  if (enEjes.length || (escena.ejes.visibles && !sueltos.length && escena.elementos.length === 0)) {
    bloques.push({
      clave: "ejes",
      ancho: tresD ? 8 : 10,
      alto: tresD ? 5 : 6,
      hondo: tresD ? 8 : 0,
      elementos: enEjes.filter((e) => visibles.has(e.id)),
      ejes: true,
    });
  }
  for (const elemento of sueltos) {
    if (!visibles.has(elemento.id)) continue;
    const tamano =
      elemento.tipo === "grafo"
        ? [8, 8, 0]
        : elemento.tipo === "molecula"
          ? [6.5, 6.5, 6.5]
          : elemento.tipo === "modelo"
            ? // Poco fondo: un órgano se mira de cerca, no desde lejos.
              [6, 6.6, 1]
            : [9, 6.6, 0];
    bloques.push({
      clave: elemento.id,
      ancho: tamano[0],
      alto: tamano[1],
      hondo: tamano[2],
      elementos: [elemento],
      ejes: false,
    });
  }
  return bloques;
}

function Camara({
  ancho,
  alto,
  hondo,
  tresD,
  frontal,
  firma,
}: {
  ancho: number;
  alto: number;
  hondo: number;
  tresD: boolean;
  frontal: boolean;
  firma: string;
}) {
  const { camera, controls, size } = useThree();
  useEffect(() => {
    const perspectiva = camera as THREE.PerspectiveCamera;
    const fov = (perspectiva.fov * Math.PI) / 180;
    const aspecto = size.width / Math.max(size.height, 1);
    // Margen de sobra por abajo: ahí flotan los deslizadores y reproductores,
    // así que el encuadre se sube un poco para que no tapen los ejes.
    const distanciaAlto = (alto * 1.5) / 2 / Math.tan(fov / 2);
    const distanciaAncho = (ancho * 1.18) / 2 / Math.tan(fov / 2) / aspecto;
    const d = Math.max(distanciaAlto, distanciaAncho, 6) + hondo / 2;
    const bajada = -alto * 0.12;
    // Un modelo anatómico se presenta de frente (vista anterior), como en
    // un atlas; el resto de escenas 3D, en diagonal para que se vea el volumen.
    if (frontal) camera.position.set(0, bajada + d * 0.08, d);
    else if (tresD) camera.position.set(d * 0.55, d * 0.5 + bajada, d * 0.75);
    else camera.position.set(0, bajada, d);
    camera.lookAt(0, bajada, 0);
    const orbita = controls as unknown as { target: THREE.Vector3; update: () => void } | null;
    if (orbita) {
      orbita.target.set(0, bajada, 0);
      orbita.update();
    }
    // Solo se reencuadra cuando cambia la composición, no cuando el alumno
    // mueve la cámara ni cuando cambia un deslizador.
  }, [firma, size.width, size.height, controls]);
  return null;
}

export interface EscenarioProps {
  escena: Escena;
  paso: EstadoDePaso;
  valores: Record<string, number>;
  fotogramas: Record<string, number>;
  enMarcha: boolean;
  reinicio: number;
  onLienzo?: (lienzo: HTMLCanvasElement) => void;
}

export function Escenario({ escena, paso, valores, fotogramas, enMarcha, reinicio, onLienzo }: EscenarioProps) {
  // Los rótulos (Html de drei) que se montan antes de que el lienzo conecte
  // sus eventos se quedan vacíos: al conectar cambian de contenedor, drei
  // desmonta su raíz de React a mitad de un commit, el desmontaje se aplaza y
  // acaba borrando la raíz nueva. Se espera a que el lienzo esté conectado.
  const [listo, setListo] = useState(false);
  const mapa = useMemo(
    () => crearMapa(escena),
    [escena.modo, JSON.stringify(escena.ejes)],
  );
  const parametros = useMemo(
    () => Object.fromEntries(escena.parametros.map((p) => [p.id, p])),
    [escena.parametros],
  );
  const bloques = useMemo(() => bloquesDe(escena, paso.visibles), [escena, paso.visibles]);
  const tresD = escena.modo === "3d" || bloques.some((b) => b.hondo > 0);
  const anchoTotal = bloques.reduce((s, b) => s + b.ancho, 0) + SEPARACION * Math.max(bloques.length - 1, 0);
  const altoTotal = Math.max(...bloques.map((b) => b.alto), 4);
  const hondoTotal = Math.max(...bloques.map((b) => b.hondo), 0);
  let cursor = -anchoTotal / 2;
  const colocados = bloques.map((bloque) => {
    const x = cursor + bloque.ancho / 2;
    cursor += bloque.ancho + SEPARACION;
    return { ...bloque, x };
  });
  const firma = `${escena.modo}|${bloques.map((b) => `${b.clave}:${b.ancho}`).join(",")}`;

  const contexto: ContextoEstudio = {
    valores,
    parametros,
    paso,
    mapa,
    fotogramas,
    enMarcha,
    reinicio,
  };

  return (
    <Canvas
      className="estudio-lienzo"
      camera={{ fov: 40, near: 0.1, far: 500, position: [0, 0, 16] }}
      dpr={[1, 2]}
      gl={{ preserveDrawingBuffer: true, antialias: true }}
      onCreated={({ gl }) => {
        onLienzo?.(gl.domElement);
        requestAnimationFrame(() => setListo(true));
      }}
    >
      <color attach="background" args={["#0b0610"]} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[6, 10, 8]} intensity={1.4} />
      <directionalLight position={[-8, -4, -6]} intensity={0.35} color="#92c7ff" />
      <Contexto.Provider value={contexto}>
        {listo && colocados.map((bloque) => (
          <group key={bloque.clave} position={[bloque.x, 0, 0]}>
            {bloque.ejes && <Ejes />}
            {bloque.elementos.map((elemento) => (
              <Aislado key={elemento.id} nombre={elemento.etiqueta}>
                <Vista elemento={elemento} />
              </Aislado>
            ))}
          </group>
        ))}
      </Contexto.Provider>
      <OrbitControls
        makeDefault
        enableRotate={tresD}
        enableDamping
        dampingFactor={0.12}
        minDistance={2}
        maxDistance={120}
      />
      <Camara
        ancho={anchoTotal}
        alto={altoTotal}
        hondo={hondoTotal}
        tresD={tresD}
        frontal={bloques.length === 1 && bloques[0].elementos[0]?.tipo === "modelo"}
        firma={firma}
      />
    </Canvas>
  );
}
