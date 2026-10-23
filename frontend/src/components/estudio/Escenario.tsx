import { Billboard, Environment, Html, Lightformer, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";

import { crearMapa } from "../../lib/estudio/ejes";
import { rama, type Herramienta, type Seleccion, type Vista3D } from "../../lib/estudio/manipulacion";
import type { Elemento, Escena, Objeto, Sistema } from "../../lib/estudio/tipos";
import { TIPOS_DE_EJES } from "../../lib/estudio/tipos";
import type { EstadoDePaso } from "../../lib/estudio/visibilidad";
import { GrafoVista, OrdenacionVista } from "./AlgoritmosVista";
import { Motor, ObjetoVista, SerieTemporal } from "./ComposicionVista";
import { Contexto, type ContextoEstudio, type Manipulacion, type Transformacion } from "./contexto";
import { Cortador, Manipulador } from "./Manipulacion";
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
    case "sistema":
      return <SerieTemporal elemento={elemento} />;
    case "objeto":
      return null; // los pinta el bloque libre, con su jerarquía
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

/**
 * Un suelo invisible que solo recibe sombras, justo debajo de lo más bajo del
 * bloque: sin él, lo que flota no tiene dónde proyectarse y no se sabe qué
 * está delante de qué. Si la escena ya tiene un suelo, este queda debajo y no
 * se ve. Se mide la caja del bloque y se recoloca si algo se mueve.
 */
function Suelo({ contenido, anima }: { contenido: React.RefObject<THREE.Group | null>; anima: boolean }) {
  const [medida, setMedida] = useState({ y: 0, ancho: 10, fondo: 10, x: 0, z: 0 });
  const caja = useMemo(() => new THREE.Box3(), []);
  const cuenta = useRef(0);
  useFrame(() => {
    cuenta.current += 1;
    if (!contenido.current || (cuenta.current > 2 && (!anima || cuenta.current % 20 !== 0))) return;
    caja.setFromObject(contenido.current);
    if (caja.isEmpty()) return;
    const centro = caja.getCenter(new THREE.Vector3());
    const tamano = caja.getSize(new THREE.Vector3());
    const nueva = {
      y: caja.min.y - 0.01,
      x: centro.x,
      z: centro.z,
      ancho: Math.max(tamano.x * 2, 4),
      fondo: Math.max(tamano.z * 2, 4),
    };
    if (
      Math.abs(nueva.y - medida.y) > 0.02 ||
      Math.abs(nueva.ancho - medida.ancho) > 0.2 ||
      Math.abs(nueva.fondo - medida.fondo) > 0.2 ||
      Math.abs(nueva.x - medida.x) > 0.2
    ) {
      setMedida(nueva);
    }
  });
  return (
    <mesh position={[medida.x, medida.y, medida.z]} rotation-x={-Math.PI / 2} receiveShadow>
      <planeGeometry args={[medida.ancho, medida.fondo]} />
      <shadowMaterial transparent opacity={0.35} />
    </mesh>
  );
}

/** Los objetos compuestos, con su jerarquía: cada uno dentro de su padre. */
function Libre({ objetos }: { objetos: Objeto[] }) {
  const contenido = useRef<THREE.Group>(null);
  const ids = new Set(objetos.map((o) => o.id));
  const hijos = new Map<string, Objeto[]>();
  const raices: Objeto[] = [];
  for (const objeto of objetos) {
    if (objeto.padre && ids.has(objeto.padre)) {
      hijos.set(objeto.padre, [...(hijos.get(objeto.padre) ?? []), objeto]);
    } else {
      raices.push(objeto);
    }
  }
  const anima = objetos.some((o) => o.anima);
  return (
    <>
      <group ref={contenido}>
        {raices.map((objeto) => (
          <Aislado key={objeto.id} nombre={objeto.etiqueta || objeto.id}>
            <ObjetoVista elemento={objeto} hijos={hijos} />
          </Aislado>
        ))}
      </group>
      <Suelo contenido={contenido} anima={anima} />
      <Cortador contenido={contenido} />
    </>
  );
}

/**
 * Luz de estudio fotográfico generada aquí mismo (sin descargar HDRIs, la PWA
 * funciona sin red): una caja de luz grande arriba, dos laterales y un
 * contraluz. Da reflejos y volumen a los materiales PBR, que con solo luces
 * direccionales parecían de plástico plano.
 */
function Iluminacion() {
  return (
    <>
      {/* El entorno da reflejos y relleno; la luz principal, forma y sombra. */}
      <Environment resolution={256} frames={1} environmentIntensity={0.55}>
        <color attach="background" args={["#14101a"]} />
        <Lightformer form="rect" intensity={2.2} position={[0, 6, 2]} rotation-x={Math.PI / 2} scale={[10, 6, 1]} />
        <Lightformer form="rect" intensity={1.4} position={[-6, 2, 3]} rotation-y={Math.PI / 2.5} scale={[4, 6, 1]} />
        <Lightformer form="rect" intensity={0.9} color="#ffe2c4" position={[6, 1.5, 3]} rotation-y={-Math.PI / 2.5} scale={[4, 6, 1]} />
        <Lightformer form="ring" intensity={0.8} color="#92c7ff" position={[0, 3, -8]} scale={4} />
      </Environment>
      <ambientLight intensity={0.25} />
      {/* La única luz con sombra: un coche sobre el suelo tiene que tocarlo. */}
      <directionalLight
        position={[6, 10, 8]}
        intensity={1.9}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.02}
        shadow-camera-left={-14}
        shadow-camera-right={14}
        shadow-camera-top={14}
        shadow-camera-bottom={-14}
        shadow-camera-near={0.5}
        shadow-camera-far={60}
      />
      <directionalLight position={[-8, -4, -6]} intensity={0.3} color="#92c7ff" />
    </>
  );
}

interface Bloque {
  clave: string;
  libre?: Objeto[];
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
  const objetos = escena.elementos.filter(
    (e): e is Objeto => e.tipo === "objeto" && visibles.has(e.id),
  );
  if (objetos.length) {
    const [ancho, alto, hondo] = escena.espacio ?? [10, 6, 6];
    bloques.push({ clave: "libre", ancho, alto, hondo, elementos: [], ejes: false, libre: objetos });
  }
  for (const elemento of sueltos) {
    if (!visibles.has(elemento.id)) continue;
    if (elemento.tipo === "objeto") continue;
    if (elemento.tipo === "sistema" && !elemento.grafica) continue;
    const tamano =
      elemento.tipo === "sistema"
        ? [9.4, 6.2, 0]
        : elemento.tipo === "grafo"
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
    // En 3D se encuadra la esfera que envuelve la caja: sumar el fondo entero
    // alejaba la cámara el doble de lo necesario en escenas anchas.
    const radio = Math.hypot(ancho, alto, hondo) / 2;
    const distanciaEsfera = (radio * 1.08) / Math.sin(fov / 2) / Math.min(aspecto, 1);
    const d = tresD && !frontal
      ? Math.max(Math.min(distanciaEsfera, Math.max(distanciaAlto, distanciaAncho) * 1.25), 6)
      : Math.max(distanciaAlto, distanciaAncho, 6) + hondo / 2;
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
  seleccion: Seleccion | null;
  herramienta: Herramienta;
  vista: Vista3D;
  /** Lo elegido no se puede mover con el gizmo (se anima con fórmulas). */
  bloqueado: boolean;
  /** Articulaciones fijadas por el alumno con su deslizador. */
  articulaciones: Record<string, number>;
  onSeleccionar: (seleccion: Seleccion | null) => void;
  onSoltar: (seleccion: Seleccion, transformacion: Transformacion) => void;
}

export function Escenario({
  escena,
  paso,
  valores,
  fotogramas,
  enMarcha,
  reinicio,
  onLienzo,
  seleccion,
  herramienta,
  vista,
  bloqueado,
  articulaciones,
  onSeleccionar,
  onSoltar,
}: EscenarioProps) {
  // Los rótulos (Html de drei) que se montan antes de que el lienzo conecte
  // sus eventos se quedan vacíos: al conectar cambian de contenedor, drei
  // desmonta su raíz de React a mitad de un commit, el desmontaje se aplaza y
  // acaba borrando la raíz nueva. Se espera a que el lienzo esté conectado.
  const [listo, setListo] = useState(false);
  const vivo = useRef<{ t: number; vars: Record<string, number> }>({ t: 0, vars: {} });
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

  const nodos = useRef(new Map<string, THREE.Object3D>());
  const lectores = useRef(new Map<string, () => Transformacion>());
  const arrastrando = useRef<string | null>(null);
  const soltado = useRef(0);
  const plano = useMemo(() => new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0), []);
  const planos = useMemo(() => (vista.corte ? [plano] : []), [vista.corte !== null, plano]);
  const aislados = useMemo(
    () =>
      vista.aislado
        ? rama(
            vista.aislado,
            escena.elementos.filter((e): e is Objeto => e.tipo === "objeto"),
          )
        : null,
    [vista.aislado, escena.elementos],
  );
  const manipulacion: Manipulacion = {
    seleccion,
    herramienta,
    vista,
    seleccionar: onSeleccionar,
    nodos,
    lectores,
    arrastrando,
    soltado,
    planos,
    aislados,
    articulaciones,
  };

  const contexto: ContextoEstudio = {
    valores,
    parametros,
    paso,
    mapa,
    fotogramas,
    enMarcha,
    reinicio,
    vivo,
    manipulacion,
  };
  const sistemas = escena.elementos.filter((e): e is Sistema => e.tipo === "sistema");

  return (
    <Canvas
      className="estudio-lienzo"
      camera={{ fov: 40, near: 0.1, far: 500, position: [0, 0, 16] }}
      dpr={[1, 2]}
      shadows="soft"
      gl={{ preserveDrawingBuffer: true, antialias: true }}
      onPointerMissed={(evento) => {
        // Soltar el gizmo también cuenta como clic en el vacío: ese no vale.
        if (evento.type === "click" && performance.now() - soltado.current > 250) onSeleccionar(null);
      }}
      onCreated={({ gl }) => {
        // El corte va por material (solo los objetos), no por todo el lienzo.
        gl.localClippingEnabled = true;
        onLienzo?.(gl.domElement);
        requestAnimationFrame(() => setListo(true));
      }}
    >
      <color attach="background" args={["#0b0610"]} />
      <Iluminacion />
      <Contexto.Provider value={contexto}>
        {listo && <Motor sistemas={sistemas} />}
        {listo && colocados.map((bloque) => (
          <group key={bloque.clave} position={[bloque.x, 0, 0]}>
            {bloque.ejes && <Ejes />}
            {bloque.libre && <Libre objetos={bloque.libre} />}
            {bloque.elementos.map((elemento) => {
              const vista = (
                <Aislado key={elemento.id} nombre={elemento.etiqueta}>
                  <Vista elemento={elemento} />
                </Aislado>
              );
              // Lo plano (gráficas, grafos, barras) mira siempre a la cámara
              // en una escena 3D; si no, al girar se ve torcido o de canto.
              return tresD && !bloque.ejes && bloque.hondo === 0 ? (
                <Billboard key={elemento.id}>{vista}</Billboard>
              ) : (
                vista
              );
            })}
          </group>
        ))}
        {listo && <Manipulador bloqueado={bloqueado} onSoltar={onSoltar} />}
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
