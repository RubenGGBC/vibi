import { Html, useGLTF } from "@react-three/drei";
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { apiUrl } from "../../lib/api";
import { getToken } from "../../lib/auth";
import { crearIntegrador, type Integrador } from "../../lib/estudio/dinamica";
import { articulacionesDe, claveArticulacion, enTopes } from "../../lib/estudio/manipulacion";
import { formatear } from "../../lib/estudio/ejes";
import { evaluar } from "../../lib/estudio/expr";
import { publicarLectura, quitarLectura } from "../../lib/estudio/lecturas";
import type { Articulacion, Objeto, Sistema } from "../../lib/estudio/tipos";
import { useAtenuado, useEstudio, useSeleccionado } from "./contexto";

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

const AMBAR = new THREE.Color("#ffb020");
const CIAN = new THREE.Color("#38bdf8");
const NEGRO = new THREE.Color("#000000");
const GRADOS = 180 / Math.PI;
const EJES = { x: new THREE.Vector3(1, 0, 0), y: new THREE.Vector3(0, 1, 0), z: new THREE.Vector3(0, 0, 1) };

/** Lo que una parte tiene por sí misma: lo del archivo, o lo que movió el alumno. */
interface Base {
  posicion: THREE.Vector3;
  rotacion: THREE.Euler;
  escala: THREE.Vector3;
}

/** Lo que se mide de cada parte al encajar el modelo. */
interface Huida {
  /** Vista explosionada: en el espacio del padre de la parte, para una explosión de 1. */
  desplazamiento: THREE.Vector3;
  /** Cuántas unidades de la escena es una unidad del padre de la parte (para deslizar). */
  escala: number;
}

/**
 * Un objeto de la biblioteca (Kenney). Se escala para que su lado más largo
 * mida `tamano[0]` y se apoya por su base: `posicion` es el centro de abajo,
 * que es como se coloca un coche en el suelo. Sus partes con nombre pueden
 * girar (ruedas), señalarse en los pasos, elegirse con el ratón y moverse.
 */
function ModeloDeBiblioteca({ elemento }: { elemento: Objeto }) {
  const { valores, vivo, paso, manipulacion: m } = useEstudio();
  const { resaltado, atenuado } = useAtenuado(elemento.id);
  const elegido = useSeleccionado(elemento.id);
  const gltf = useGLTF(apiUrl(elemento.url ?? ""), false, false, (loader) => {
    const token = getToken();
    if (token) loader.setRequestHeader({ Authorization: `Bearer ${token}` });
  });

  // Una copia propia (el mismo coche puede salir dos veces) con materiales
  // propios por malla, para poder resaltar una rueda sin encender las demás.
  const { raiz, mallas, porNombre, delArchivo, colorOriginal, ladoOriginal } = useMemo(() => {
    const copia = gltf.scene.clone(true);
    const mallas: THREE.Mesh[] = [];
    const colorOriginal = new Map<THREE.Material, THREE.Color>();
    const ladoOriginal = new Map<THREE.Material, THREE.Side>();
    copia.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.material = Array.isArray(o.material)
          ? o.material.map((m) => m.clone())
          : (o.material as THREE.Material).clone();
        for (const material of Array.isArray(o.material) ? o.material : [o.material]) {
          const estandar = material as THREE.MeshStandardMaterial;
          if (estandar.color) colorOriginal.set(material, estandar.color.clone());
          ladoOriginal.set(material, material.side);
        }
        mallas.push(o);
      }
    });
    const porNombre = new Map<string, THREE.Object3D>();
    copia.traverse((o) => {
      if (o.name) porNombre.set(o.name, o);
    });
    const delArchivo = new Map<THREE.Object3D, Base>();
    for (const o of porNombre.values()) {
      delArchivo.set(o, { posicion: o.position.clone(), rotacion: o.rotation.clone(), escala: o.scale.clone() });
    }
    const raiz = new THREE.Group();
    raiz.add(copia);
    return { raiz, mallas, porNombre, delArchivo, colorOriginal, ladoOriginal };
  }, [gltf]);

  // Parte (nombre en `partes`) → su nodo. three limpia los nombres al cargar.
  const nodoDeParte = useMemo(() => {
    const mapa = new Map<string, THREE.Object3D>();
    for (const parte of Object.keys(elemento.partes ?? {})) {
      const nodo = porNombre.get(THREE.PropertyBinding.sanitizeNodeName(parte));
      if (nodo) mapa.set(parte, nodo);
    }
    return mapa;
  }, [porNombre, elemento.partes]);

  // El tamaño puede depender de un deslizador: se reencaja cuando cambia.
  const largo = Math.max(vector(elemento.tamano, { ...valores, t: 0, ...vivo.current.vars }, 2)[0], 1e-3);
  const [alto, setAlto] = useState(0);
  const huidas = useRef(new Map<THREE.Object3D, Huida>());
  useEffect(() => {
    const copia = raiz.children[0];
    copia.position.set(0, 0, 0);
    copia.scale.setScalar(1);
    // Se mide suelto, en su propio espacio y con las partes en su sitio de
    // fábrica: colgado del grupo, la caja saldría en coordenadas del mundo,
    // con el objeto ya movido, girado o explosionado.
    raiz.remove(copia);
    for (const [nodo, base] of delArchivo) {
      nodo.position.copy(base.posicion);
      nodo.rotation.copy(base.rotacion);
      nodo.scale.copy(base.escala);
    }
    copia.updateMatrixWorld(true);
    const caja = new THREE.Box3().setFromObject(copia);
    const medida = caja.getSize(new THREE.Vector3());
    const centro = caja.getCenter(new THREE.Vector3());
    const mayor = Math.max(medida.x, medida.y, medida.z, 1e-6);
    // Cada parte se aleja del centro del modelo en la dirección en la que
    // está, y un poco más cuanto más lejos: las del centro también se separan.
    huidas.current.clear();
    for (const nodo of nodoDeParte.values()) {
      if (!nodo.parent) continue;
      const suya = new THREE.Box3().setFromObject(nodo);
      if (suya.isEmpty()) continue;
      const direccion = suya.getCenter(new THREE.Vector3()).sub(centro);
      if (direccion.lengthSq() < 1e-8) direccion.set(0, 1, 0).multiplyScalar(1e-4);
      const empuje = direccion.clone().normalize().multiplyScalar(mayor * 0.35).add(direccion.multiplyScalar(0.8));
      const alPadre = new THREE.Matrix3().setFromMatrix4(nodo.parent.matrixWorld).invert();
      const escalaPadre = nodo.parent.getWorldScale(new THREE.Vector3()).x;
      huidas.current.set(nodo, {
        desplazamiento: empuje.applyMatrix3(alPadre),
        escala: (escalaPadre * largo) / mayor,
      });
    }
    raiz.add(copia);
    const escala = largo / mayor;
    copia.scale.setScalar(escala);
    copia.position.set(-centro.x * escala, -caja.min.y * escala, -centro.z * escala);
    setAlto(medida.y * escala);
  }, [raiz, largo, delArchivo, nodoDeParte]);

  // Lo propio de cada parte: lo del archivo, salvo lo que el alumno movió.
  const bases = useMemo(() => {
    const mapa = new Map<THREE.Object3D, Base>();
    for (const [parte, nodo] of nodoDeParte) {
      const deFabrica = delArchivo.get(nodo);
      if (!deFabrica) continue;
      const ajuste = elemento.ajustes?.[parte];
      mapa.set(nodo, {
        posicion: ajuste?.posicion ? new THREE.Vector3(...ajuste.posicion) : deFabrica.posicion,
        rotacion: ajuste?.rotacion
          ? new THREE.Euler(...(ajuste.rotacion.map((g) => g / GRADOS) as [number, number, number]))
          : deFabrica.rotacion,
        escala: ajuste?.escala ? new THREE.Vector3(...ajuste.escala) : deFabrica.escala,
      });
    }
    return mapa;
  }, [nodoDeParte, delArchivo, elemento.ajustes]);

  const partesResaltadas = useMemo(() => {
    const pedidas = new Set(paso.partes.get(elemento.id) ?? []);
    const nombres = new Set<string>();
    for (const [malla, etiqueta] of Object.entries(elemento.partes ?? {})) {
      if (pedidas.has(malla) || pedidas.has(etiqueta)) nombres.add(malla);
    }
    return nombres;
  }, [paso, elemento.id, elemento.partes]);

  useEffect(() => {
    const deMalla = (partes: Iterable<string>) => {
      const mallasDe = new Set<THREE.Object3D>();
      for (const parte of partes) nodoDeParte.get(parte)?.traverse((o) => mallasDe.add(o));
      return mallasDe;
    };
    const encendidas = deMalla(partesResaltadas);
    const elegidas = elegido.parte ? deMalla([elegido.parte]) : new Set<THREE.Object3D>();
    const coloreadas = new Map<THREE.Object3D, THREE.Color>();
    for (const [parte, ajuste] of Object.entries(elemento.ajustes ?? {})) {
      if (!ajuste.color) continue;
      const color = new THREE.Color(ajuste.color);
      for (const o of deMalla([parte])) coloreadas.set(o, color);
    }
    const opacidad = elemento.opacidad * (atenuado ? 0.25 : 1);
    const cortando = m.planos.length > 0;
    for (const malla of mallas) {
      const seleccion = elegido.objeto || elegidas.has(malla);
      const encendida = resaltado && partesResaltadas.size === 0 ? true : encendidas.has(malla);
      for (const material of Array.isArray(malla.material) ? malla.material : [malla.material]) {
        const estandar = material as THREE.MeshStandardMaterial;
        estandar.transparent = opacidad < 1;
        estandar.opacity = opacidad;
        // Lo atenuado no escribe profundidad: si no, tapa lo resaltado de detrás.
        estandar.depthWrite = opacidad >= 1;
        if (estandar.emissive) {
          estandar.emissive.copy(seleccion ? CIAN : encendida ? AMBAR : NEGRO);
          estandar.emissiveIntensity = seleccion ? 0.45 : encendida ? 0.55 : 0;
        }
        const original = colorOriginal.get(material);
        if (estandar.color && original) estandar.color.copy(coloreadas.get(malla) ?? original);
        // Cortado se ve el interior: hacen falta las caras de dentro.
        estandar.clippingPlanes = m.planos;
        estandar.side = cortando ? THREE.DoubleSide : ladoOriginal.get(material) ?? THREE.FrontSide;
        estandar.needsUpdate = true;
      }
      malla.castShadow = true;
      malla.receiveShadow = true;
    }
  }, [
    mallas, nodoDeParte, partesResaltadas, resaltado, atenuado, elemento.opacidad, elemento.ajustes,
    elegido.objeto, elegido.parte, m.planos, colorOriginal, ladoOriginal,
  ]);

  // Las partes, para el gizmo: su nodo y cómo leer lo propio de cada una.
  const aplicado = useRef(
    new Map<THREE.Object3D, { empuje: THREE.Vector3; giro: { eje: "x" | "y" | "z"; angulo: number } | null }>(),
  );
  useEffect(() => {
    const claves: string[] = [];
    for (const [parte, nodo] of nodoDeParte) {
      const k = `${elemento.id}.${parte}`;
      claves.push(k);
      m.nodos.current.set(k, nodo);
      m.lectores.current.set(k, () => {
        const puesto = aplicado.current.get(nodo);
        const posicion = nodo.position.clone().sub(puesto?.empuje ?? new THREE.Vector3());
        // Se deshace el giro de la articulación, que va sobre el eje propio.
        const cuaternion = nodo.quaternion.clone();
        if (puesto?.giro) {
          cuaternion.multiply(new THREE.Quaternion().setFromAxisAngle(EJES[puesto.giro.eje], -puesto.giro.angulo));
        }
        const rotacion = new THREE.Euler().setFromQuaternion(cuaternion);
        return {
          posicion: posicion.toArray(),
          rotacion: [rotacion.x, rotacion.y, rotacion.z].map((r) => r * GRADOS),
          escala: nodo.scale.toArray(),
        };
      });
    }
    return () => {
      for (const k of claves) {
        m.nodos.current.delete(k);
        m.lectores.current.delete(k);
      }
    };
  }, [nodoDeParte, elemento.id, m.nodos, m.lectores]);

  const movimientos = useMemo(() => {
    const porNodo = new Map<THREE.Object3D, { articulacion: Articulacion; clave: string }>();
    articulacionesDe(elemento).forEach((articulacion, i) => {
      for (const parte of articulacion.partes) {
        const nodo = nodoDeParte.get(parte);
        if (nodo) porNodo.set(nodo, { articulacion, clave: claveArticulacion(elemento.id, i) });
      }
    });
    return porNodo;
  }, [elemento, nodoDeParte]);

  const giroTemporal = useMemo(() => new THREE.Quaternion(), []);
  useFrame(() => {
    const scope = { ...valores, t: vivo.current.t, ...vivo.current.vars };
    const explosion = m.vista.explosion;
    for (const [parte, nodo] of nodoDeParte) {
      const base = bases.get(nodo);
      if (!base) continue;
      nodo.visible = !elemento.ajustes?.[parte]?.oculta && !m.vista.ocultos.has(`${elemento.id}.${parte}`);
      if (m.arrastrando.current === `${elemento.id}.${parte}`) continue;
      const huida = huidas.current.get(nodo);
      const empuje = (huida?.desplazamiento ?? new THREE.Vector3()).clone().multiplyScalar(explosion);
      nodo.rotation.copy(base.rotacion);
      nodo.scale.copy(base.escala);
      let giro = null;
      const movimiento = movimientos.get(nodo);
      if (movimiento) {
        const { articulacion, clave: k } = movimiento;
        // Lo que fija el alumno con su deslizador manda sobre la fórmula.
        const valor = enTopes(m.articulaciones[k] ?? vector([articulacion.valor], scope)[0], articulacion);
        // Sobre el eje propio de la pieza (el de su bisagra), no el del padre.
        if (articulacion.tipo === "giro") {
          const angulo = (valor * Math.PI) / 180;
          nodo.quaternion.multiply(giroTemporal.setFromAxisAngle(EJES[articulacion.eje], angulo));
          giro = { eje: articulacion.eje, angulo };
        } else {
          const direccion = EJES[articulacion.eje].clone().applyEuler(base.rotacion);
          empuje.addScaledVector(direccion, valor / Math.max(huida?.escala ?? 1, 1e-6));
        }
      }
      nodo.position.copy(base.posicion).add(empuje);
      aplicado.current.set(nodo, { empuje, giro });
    }
  });

  // Un clic elige el modelo; otro clic sobre el modelo ya elegido, la parte.
  const alClicar = (evento: ThreeEvent<MouseEvent>) => {
    if (evento.delta > 4) return;
    evento.stopPropagation();
    let parte: string | null = null;
    for (let o: THREE.Object3D | null = evento.object; o && o !== raiz; o = o.parent) {
      const encontrada = [...nodoDeParte].find(([, nodo]) => nodo === o);
      if (encontrada) {
        parte = encontrada[0];
        break;
      }
    }
    // El mismo clic sobre la parte ya elegida vuelve al modelo entero.
    const yaElegido = m.seleccion?.id === elemento.id;
    const otraParte = parte !== null && m.seleccion?.parte !== parte;
    m.seleccionar({ id: elemento.id, parte: yaElegido && otraParte ? parte : null });
  };

  const { atenuado: sinRotulo } = useAtenuado(elemento.id);
  const nombreDeParte = elegido.parte ? elemento.partes?.[elegido.parte] ?? elegido.parte : null;
  return (
    <>
      <primitive object={raiz} onClick={alClicar} />
      {/* El nombre, encima: en la base quedaría dentro del objeto. */}
      {elemento.etiqueta && !sinRotulo && alto > 0 && (
        <Html position={[0, alto, 0]} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
          <span
            className="estudio-rotulo es-nombre"
            style={{ color: elemento.color, display: "inline-block", transform: "translateY(-1.1rem)" }}
          >
            {elemento.etiqueta}
            {nombreDeParte && <small> · {nombreDeParte}</small>}
          </span>
        </Html>
      )}
    </>
  );
}

export function ObjetoVista({ elemento, hijos }: { elemento: Objeto; hijos: Map<string, Objeto[]> }) {
  const { valores, vivo, manipulacion: m } = useEstudio();
  const { resaltado, atenuado } = useAtenuado(elemento.id);
  const elegido = useSeleccionado(elemento.id).objeto;
  const nodo = useRef<THREE.Group>(null);
  const cuerpo = useRef<THREE.Object3D>(null);
  const flecha = useRef<THREE.Group>(null);

  // El gizmo se cuelga de este nodo: su posición es la de `posicion`, en el
  // espacio del padre, así que lo que deja el gizmo se guarda tal cual.
  useEffect(() => {
    const propio = nodo.current;
    if (!propio) return;
    m.nodos.current.set(elemento.id, propio);
    m.lectores.current.set(elemento.id, () => ({
      posicion: propio.position.toArray(),
      rotacion: [propio.rotation.x, propio.rotation.y, propio.rotation.z].map((r) => r * GRADOS),
      escala: propio.scale.toArray(),
    }));
    return () => {
      m.nodos.current.delete(elemento.id);
      m.lectores.current.delete(elemento.id);
    };
  }, [elemento.id, m.nodos, m.lectores]);

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
    if (nodo.current && m.arrastrando.current !== elemento.id) {
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

  const cortando = m.planos.length > 0;
  const material = (
    <meshStandardMaterial
      color={elemento.color}
      emissive={elegido ? "#38bdf8" : resaltado ? "#ffb020" : elemento.color}
      emissiveIntensity={elegido ? 0.5 : resaltado ? 0.6 : elemento.brillo}
      transparent={elemento.opacidad < 1 || atenuado}
      opacity={elemento.opacidad * (atenuado ? 0.25 : 1)}
      side={elemento.forma === "plano" || cortando ? THREE.DoubleSide : THREE.FrontSide}
      clippingPlanes={m.planos}
      roughness={0.5}
    />
  );

  // Un clic lo elige; el más profundo gana (el satélite, no el planeta).
  const alClicar = (evento: ThreeEvent<MouseEvent>) => {
    if (evento.delta > 4) return;
    evento.stopPropagation();
    m.seleccionar({ id: elemento.id, parte: null });
  };
  // Aislado otro objeto, este no se pinta, pero lo que cuelga de él puede que sí.
  const propioVisible = !m.aislados || m.aislados.has(elemento.id);

  return (
    <group ref={nodo} visible={!m.vista.ocultos.has(elemento.id)}>
      <group visible={propioVisible} onClick={elemento.forma === "modelo" ? undefined : alClicar}>
        {geometria && (
          <mesh ref={cuerpo as React.RefObject<THREE.Mesh>} geometry={geometria} castShadow receiveShadow>
            {material}
          </mesh>
        )}
        {elemento.forma === "modelo" && elemento.url && (
          <Suspense
            fallback={
              <Html center>
                <span className="estudio-rotulo es-nota">Cargando {elemento.etiqueta || elemento.modelo}…</span>
              </Html>
            }
          >
            <ModeloDeBiblioteca elemento={elemento} />
          </Suspense>
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
        {elemento.etiqueta && elemento.forma !== "texto" && elemento.forma !== "modelo" && !atenuado && (
          <Html center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
            <span
              className="estudio-rotulo es-nombre"
              style={{ color: elemento.color, display: "inline-block", transform: "translateY(-1.5rem)" }}
            >
              {elemento.etiqueta}
            </span>
          </Html>
        )}
      </group>
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
