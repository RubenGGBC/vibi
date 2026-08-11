import * as THREE from "three";

import {
  acotar,
  avanzarMuelle,
  crearMuelle,
  crearRitmo,
  crearSeguimientoPuntero,
  fijarMuelle,
  pulso,
  type Muelle,
} from "./faceMotion";

/**
 * La cara de Vibi en 3D.
 *
 * El módulo no sabe nada de React: recibe un contenedor, monta una escena de
 * Three.js dentro y expone `setState`, `resize` y `dispose`. Así la lógica de
 * voz de `FacePanel` no se mezcla con WebGL y esto se puede probar aparte.
 */

/**
 * Los cuatro primeros son el ciclo de voz y los usan las dos caras. Los cinco
 * siguientes cuentan lo que pasa en el resto de Vibi —una herramienta en
 * marcha, un permiso pendiente, algo roto, algo que salió bien, el servidor
 * caído— y de momento solo los usa el companion.
 */
export type FaceVoiceState = "idle" | "listening" | "thinking" | "speaking";

export type FaceState =
  | FaceVoiceState
  | "working"
  | "waiting"
  | "alert"
  | "pleased"
  | "offline";

/** Las bocas que sabe poner. Cada una es una malla; lo que se cruza es su peso. */
type FormaBoca = "w" | "sonrisa" | "linea" | "o" | "mueca";

/**
 * `web` es la cara de siempre, la que sale en la PWA. `companion` es la del
 * escritorio: la misma gata, pero con muelles en vez de interpolación plana,
 * mirada al cursor y tics de reposo. Se separan porque en la PWA la cara es un
 * elemento más de una página y aquí es lo único que hay en la ventana.
 */
export type FacePerfil = "web" | "companion";

export interface FaceSceneOptions {
  perfil?: FacePerfil;
}

export interface FaceScene {
  setState(state: FaceState): void;
  /** Adónde mira, en coordenadas del contenedor de -1 a 1. Solo en `companion`. */
  setPointer(x: number, y: number): void;
  /** El ratón se fue: vuelve a la mirada suelta. */
  clearPointer(): void;
  resize(): void;
  dispose(): void;
}

/** Los mismos tonos que las variables CSS de `.face-page`. El pelaje se aclara
 *  respecto al SVG (#16121f) porque el sombreado toon necesita algo de rango. */
const PALETTE = {
  fur: 0x2a2240,
  furLight: 0x3a2f57,
  border: 0x6d5bd0,
  lavender: 0xa78bfa,
  lavenderSoft: 0xd6c9ff,
  pink: 0xf0abfc,
  blush: 0xc084fc,
  white: 0xffffff,
  /** La pupila: violeta muy oscuro, no negro, para no romper la paleta. */
  pupil: 0x1b1230,
  amber: 0xffc46e,
  alarm: 0xff7b97,
};

interface Pose {
  headZ: number;
  headX: number;
  ears: number;
  /** Tamaño del ojo. Los párpados mandan en cuánto se ve; esto en cuán grande es. */
  eyeX: number;
  eyeY: number;
  /** Cuánto baja el párpado de arriba (0 abierto, 1 cerrado). */
  lidTop: number;
  /** Cuánto sube el de abajo. Entrecerrar de verdad usa los dos. */
  lidBottom: number;
  /** Altura de las cejas: arriba sorpresa, abajo concentración. */
  browY: number;
  /** Inclinación: positivo sube la punta de dentro (pena, súplica); negativo, ceño. */
  browTilt: number;
  /** Escala de la pupila. Dilatada es interés; contraída, alarma. */
  pupil: number;
  gazeX: number;
  gazeY: number;
  blush: number;
  happy: number;
  dots: number;
  ring: number;
  bobAmp: number;
  bobSpeed: number;
}

/**
 * El catálogo de expresiones. Los cuatro primeros estados son los de siempre,
 * los que también usa la cara de la PWA; el resto los estrena el companion para
 * poder contar lo que pasa en el resto de Vibi sin escribir una línea.
 */
const POSES: Record<FaceState, Pose> = {
  idle: {
    headZ: 0, headX: 0, ears: 0, eyeX: 1, eyeY: 1,
    lidTop: 0, lidBottom: 0, browY: 0, browTilt: 0, pupil: 1,
    gazeX: 0, gazeY: 0, blush: 0, happy: 0,
    dots: 0, ring: 0, bobAmp: 0.09, bobSpeed: 1.2,
  },
  listening: {
    headZ: 0.1, headX: 0.02, ears: 0.26, eyeX: 1.18, eyeY: 1.2,
    lidTop: 0, lidBottom: 0, browY: 0.05, browTilt: 0.06, pupil: 1.2,
    gazeX: 0, gazeY: 0.01, blush: 0.4, happy: 0,
    dots: 0, ring: 1, bobAmp: 0.05, bobSpeed: 1.9,
  },
  thinking: {
    headZ: -0.07, headX: -0.07, ears: -0.14, eyeX: 1, eyeY: 1,
    lidTop: 0.42, lidBottom: 0.12, browY: 0.02, browTilt: 0.3, pupil: 0.92,
    gazeX: 0.045, gazeY: 0.05, blush: 0, happy: 0,
    dots: 1, ring: 0, bobAmp: 0.05, bobSpeed: 0.75,
  },
  speaking: {
    headZ: 0, headX: 0.03, ears: 0.1, eyeX: 1, eyeY: 1,
    lidTop: 0, lidBottom: 0, browY: 0.04, browTilt: 0, pupil: 1,
    gazeX: 0, gazeY: 0, blush: 0.6, happy: 1,
    dots: 0, ring: 0, bobAmp: 0.11, bobSpeed: 5.2,
  },
  // Manos a la obra: cejas bajas, ojos entornados, boca recta. Se distingue de
  // `thinking` en que aquí no duda, está haciendo algo.
  working: {
    headZ: 0.02, headX: -0.03, ears: -0.06, eyeX: 0.96, eyeY: 0.98,
    lidTop: 0.3, lidBottom: 0.18, browY: -0.07, browTilt: -0.18, pupil: 0.88,
    gazeX: 0, gazeY: -0.02, blush: 0, happy: 0,
    dots: 1, ring: 0, bobAmp: 0.04, bobSpeed: 1.5,
  },
  // Espera algo de ti: te busca la cara, cejas en súplica, quieta.
  waiting: {
    headZ: 0.06, headX: 0.05, ears: 0.3, eyeX: 1.16, eyeY: 1.22,
    lidTop: 0, lidBottom: 0, browY: 0.12, browTilt: 0.42, pupil: 1.3,
    gazeX: 0, gazeY: 0.02, blush: 0.3, happy: 0,
    dots: 0, ring: 1, bobAmp: 0.035, bobSpeed: 1.1,
  },
  // Algo ha salido mal: ceño, orejas atrás, pupila contraída.
  alert: {
    headZ: -0.04, headX: 0.06, ears: -0.34, eyeX: 1.1, eyeY: 1.05,
    lidTop: 0.06, lidBottom: 0.24, browY: -0.12, browTilt: -0.46, pupil: 0.62,
    gazeX: 0, gazeY: 0, blush: 0, happy: 0,
    dots: 0, ring: 0, bobAmp: 0.06, bobSpeed: 2.4,
  },
  // Ha salido bien: ojos felices, orejas arriba y algo de rebote.
  pleased: {
    headZ: 0.03, headX: 0.05, ears: 0.34, eyeX: 1, eyeY: 1,
    lidTop: 0, lidBottom: 0, browY: 0.1, browTilt: 0.08, pupil: 1.15,
    gazeX: 0, gazeY: 0, blush: 0.8, happy: 1,
    dots: 0, ring: 0, bobAmp: 0.13, bobSpeed: 3.4,
  },
  // Sin servidor: ojos a media asta, orejas caídas, nada que la anime.
  offline: {
    headZ: -0.02, headX: -0.12, ears: -0.42, eyeX: 0.94, eyeY: 0.9,
    lidTop: 0.58, lidBottom: 0.2, browY: -0.04, browTilt: 0.22, pupil: 0.8,
    gazeX: 0, gazeY: -0.06, blush: 0, happy: 0,
    dots: 0, ring: 0, bobAmp: 0.03, bobSpeed: 0.55,
  },
};

const FORMAS: readonly FormaBoca[] = ["w", "sonrisa", "linea", "o", "mueca"];

/** Qué boca lleva cada estado. Va aparte porque una forma no se interpola: lo
 *  que se cruza es el peso de cada malla, no la geometría. */
const BOCA: Record<FaceState, FormaBoca> = {
  idle: "w",
  listening: "w",
  thinking: "mueca",
  speaking: "o",
  working: "linea",
  waiting: "w",
  alert: "mueca",
  pleased: "sonrisa",
  offline: "linea",
};

/**
 * Las claves que pueden pasarse de frenada al cambiar de estado: postura,
 * orejas, ojos, ritmo del flotar. Las demás —opacidades y conmutadores como
 * `talking` o `dots`— llegan sin rebote, porque pasarse de 1 o bajar de 0 en un
 * material se ve como un parpadeo sucio, no como peso.
 */
const ELASTICAS: ReadonlySet<keyof Pose> = new Set([
  "headZ",
  "headX",
  "ears",
  "eyeX",
  "eyeY",
  "lidTop",
  "lidBottom",
  "browY",
  "browTilt",
  "pupil",
  "gazeX",
  "gazeY",
  "bobAmp",
  "bobSpeed",
]);

const RIGIDEZ = 190;
/** Por debajo de `2 * sqrt(RIGIDEZ)` (≈27,6) el muelle se pasa y vuelve. */
const AMORTIGUACION_ELASTICA = 19;
const AMORTIGUACION_FIRME = 27.6;

export function supportsWebGL(): boolean {
  try {
    const probe = document.createElement("canvas");
    return Boolean(probe.getContext("webgl2") ?? probe.getContext("webgl"));
  } catch {
    return false;
  }
}

const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

export function createFaceScene(
  container: HTMLElement,
  options?: FaceSceneOptions,
): FaceScene | null {
  if (!supportsWebGL()) return null;
  const vivo = options?.perfil === "companion";

  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch {
    return null;
  }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
  camera.position.set(0, 0.1, 8.2);
  camera.lookAt(0, 0.05, 0);

  // Ambiente flojo a propósito: si sube mucho, aplana las bandas del toon.
  scene.add(new THREE.AmbientLight(PALETTE.border, 0.6));
  const keyLight = new THREE.DirectionalLight(0xfff4ff, 2);
  keyLight.position.set(2.5, 3, 4);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(PALETTE.lavender, 1.2);
  rimLight.position.set(-3.5, 0.6, -2);
  scene.add(rimLight);

  // --- materiales -----------------------------------------------------------
  const toonRamp = (() => {
    const levels = 3;
    const data = new Uint8Array(levels);
    for (let i = 0; i < levels; i += 1) data[i] = Math.round((i / (levels - 1)) * 255);
    const texture = new THREE.DataTexture(data, levels, 1, THREE.RedFormat);
    texture.minFilter = THREE.NearestFilter;
    texture.magFilter = THREE.NearestFilter;
    texture.generateMipmaps = false;
    texture.needsUpdate = true;
    return texture;
  })();

  const toon = (color: number) => new THREE.MeshToonMaterial({ color, gradientMap: toonRamp });
  const flat = (color: number, opacity = 1) =>
    new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity });

  /** Contorno cel-shading por casco invertido. Va como hijo de la malla para
   *  heredar cualquier transformación que le apliquemos después. */
  const outline = (mesh: THREE.Mesh, thickness = 1.07) => {
    const hull = new THREE.Mesh(
      mesh.geometry,
      new THREE.MeshBasicMaterial({ color: PALETTE.border, side: THREE.BackSide }),
    );
    hull.scale.setScalar(thickness);
    mesh.add(hull);
  };

  // --- la gata --------------------------------------------------------------
  const cat = new THREE.Group();
  scene.add(cat);

  const head = new THREE.Mesh(new THREE.SphereGeometry(1.4, 56, 40), toon(PALETTE.fur));
  head.scale.set(1.06, 1, 0.9);
  outline(head, 1.05);
  cat.add(head);

  const muzzle = new THREE.Mesh(new THREE.SphereGeometry(0.52, 32, 24), toon(PALETTE.furLight));
  muzzle.scale.set(1.05, 0.72, 0.62);
  muzzle.position.set(0, -0.34, 1.02);
  cat.add(muzzle);

  // orejas: el pivote va en la base para que el giro salga natural
  const makeEar = (side: number): THREE.Group => {
    const pivot = new THREE.Group();
    pivot.position.set(0.82 * side, 0.95, 0.12);
    pivot.rotation.z = -0.3 * side;
    pivot.rotation.x = -0.16;

    const outer = new THREE.Mesh(new THREE.ConeGeometry(0.5, 1.05, 4), toon(PALETTE.fur));
    outer.position.y = 0.5;
    outer.rotation.y = Math.PI / 4;
    outline(outer, 1.08);
    pivot.add(outer);

    const inner = new THREE.Mesh(
      new THREE.ConeGeometry(0.3, 0.62, 4),
      flat(PALETTE.lavender, 0.42),
    );
    inner.position.set(0, 0.42, 0.14);
    inner.rotation.y = Math.PI / 4;
    pivot.add(inner);

    cat.add(pivot);
    return pivot;
  };
  const earLeft = makeEar(-1);
  const earRight = makeEar(1);

  /**
   * Ojos con párpados de verdad.
   *
   * Antes el parpadeo era un `scale.y` del ojo entero: se aplastaba hacia su
   * centro, que no es lo que hace un ojo. Ahora hay dos tapas del color del
   * pelaje que entran desde arriba y desde abajo, así que se puede cerrar de
   * verdad, entrecerrar solo por arriba (sospecha) o dejar el ojo a media asta
   * (sueño). La pupila va aparte para poder dilatarla.
   */
  const makeEye = (side: number) => {
    const eye = new THREE.Group();
    eye.position.set(0.52 * side, 0.16, 1.1);
    eye.rotation.y = 0.34 * side;

    const inner = new THREE.Group(); // posición -> mirada
    eye.add(inner);

    const globe = new THREE.Mesh(new THREE.SphereGeometry(0.23, 32, 24), flat(PALETTE.lavender));
    globe.scale.set(1, 1.24, 0.5);
    inner.add(globe);

    const pupil = new THREE.Mesh(new THREE.SphereGeometry(0.115, 24, 18), flat(PALETTE.pupil));
    pupil.position.z = 0.06;
    pupil.scale.set(1, 1.15, 0.4);
    inner.add(pupil);

    const shineMain = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), flat(PALETTE.white));
    shineMain.position.set(0.08 * side, 0.1, 0.14);
    shineMain.scale.z = 0.5;
    inner.add(shineMain);

    const shineSoft = new THREE.Mesh(
      new THREE.SphereGeometry(0.042, 16, 12),
      flat(PALETTE.lavenderSoft),
    );
    shineSoft.position.set(-0.07 * side, -0.11, 0.14);
    shineSoft.scale.z = 0.5;
    inner.add(shineSoft);

    // Las tapas son del material de la cabeza, no un color plano: así reciben
    // la misma luz que el resto de la cara y no se leen como un parche pegado.
    const makeLid = (direccion: number): THREE.Mesh => {
      const lid = new THREE.Mesh(new THREE.SphereGeometry(0.3, 24, 16), toon(PALETTE.fur));
      lid.scale.set(1.15, 1, 0.45);
      // En reposo descansa justo fuera del ojo, camuflada contra el pelaje.
      lid.position.set(0, direccion * 0.56, 0.04);
      eye.add(lid);
      return lid;
    };
    const lidTop = makeLid(1);
    const lidBottom = makeLid(-1);

    cat.add(eye);
    return { eye, inner, pupil, lidTop, lidBottom };
  };
  const eyeLeft = makeEye(-1);
  const eyeRight = makeEye(1);

  // ojos felices ^ ^, solo al hablar
  const makeArc = (side: number): THREE.Mesh => {
    const arc = new THREE.Mesh(
      new THREE.TorusGeometry(0.2, 0.04, 10, 28, Math.PI),
      flat(PALETTE.lavender),
    );
    arc.position.set(0.52 * side, 0.14, 1.18);
    arc.rotation.y = 0.34 * side;
    arc.visible = false;
    cat.add(arc);
    return arc;
  };
  const arcLeft = makeArc(-1);
  const arcRight = makeArc(1);

  /**
   * Cejas. Sin ellas no hay duda, ni sospecha, ni preocupación: los ojos solos
   * dan como mucho abierto y cerrado. Van sobre un pivote en el extremo
   * interior para que al inclinarse sea la punta de dentro la que sube o baja,
   * como en una cara de verdad.
   */
  const makeBrow = (side: number): THREE.Group => {
    const pivot = new THREE.Group();
    pivot.position.set(0.52 * side, 0.62, 1.16);
    pivot.rotation.y = 0.34 * side;

    const brow = new THREE.Mesh(
      new THREE.CapsuleGeometry(0.035, 0.3, 4, 10),
      flat(PALETTE.border),
    );
    brow.rotation.z = Math.PI / 2;
    brow.scale.z = 0.5;
    pivot.add(brow);

    cat.add(pivot);
    return pivot;
  };
  const browLeft = makeBrow(-1);
  const browRight = makeBrow(1);

  const makeBlush = (side: number): THREE.Mesh => {
    const cheek = new THREE.Mesh(new THREE.SphereGeometry(0.24, 20, 16), flat(PALETTE.blush, 0));
    cheek.position.set(0.82 * side, -0.26, 0.98);
    cheek.scale.set(1, 0.55, 0.25);
    cat.add(cheek);
    return cheek;
  };
  const blushLeft = makeBlush(-1);
  const blushRight = makeBlush(1);

  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.13, 0.14, 3), flat(PALETTE.pink));
  nose.position.set(0, -0.19, 1.32);
  nose.rotation.x = Math.PI; // el triangulito apunta hacia abajo
  nose.scale.z = 0.55;
  cat.add(nose);

  /**
   * La boca, por formas.
   *
   * Antes había exactamente dos —la `w` de reposo y el hueco de hablar— y se
   * encendía una u otra, así que no existía nada entre medias ni ninguna otra
   * cosa que pudiera decir la boca. Ahora cada forma es una malla con su peso;
   * el peso manda en su opacidad y su escala, y las formas se cruzan en vez de
   * conmutar. Añadir una expresión es añadir una malla más aquí.
   */
  const mouth = new THREE.Group();
  mouth.position.set(0, -0.43, 1.32);
  cat.add(mouth);

  const shapes = {} as Record<FormaBoca, THREE.Group>;
  const registrar = (nombre: FormaBoca, grupo: THREE.Group) => {
    // Los materiales nacen opacos; para poder cruzarlas por opacidad hay que
    // marcarlos transparentes aquí, o el peso no se notaría hasta desaparecer.
    grupo.traverse((objeto) => {
      if (objeto instanceof THREE.Mesh) {
        const material = objeto.material as THREE.MeshBasicMaterial;
        material.transparent = true;
        material.opacity = 0;
      }
    });
    grupo.scale.setScalar(0.001);
    grupo.visible = false;
    mouth.add(grupo);
    shapes[nombre] = grupo;
  };

  // `w`: los dos arquitos de gato que se tocan en el centro.
  const formaW = new THREE.Group();
  for (const side of [-1, 1]) {
    const curve = new THREE.Mesh(
      new THREE.TorusGeometry(0.11, 0.028, 8, 20, Math.PI),
      flat(PALETTE.lavender),
    );
    curve.rotation.z = Math.PI;
    curve.position.x = 0.11 * side;
    formaW.add(curve);
  }
  registrar("w", formaW);

  // `sonrisa`: un solo arco ancho hacia arriba.
  const formaSonrisa = new THREE.Group();
  const sonrisa = new THREE.Mesh(
    new THREE.TorusGeometry(0.17, 0.03, 8, 26, Math.PI),
    flat(PALETTE.lavender),
  );
  sonrisa.rotation.z = Math.PI;
  formaSonrisa.add(sonrisa);
  registrar("sonrisa", formaSonrisa);

  // `linea`: boca recta, para cuando la cosa va en serio.
  const formaLinea = new THREE.Group();
  const linea = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.028, 0.24, 4, 8),
    flat(PALETTE.lavender),
  );
  linea.rotation.z = Math.PI / 2;
  linea.scale.z = 0.5;
  formaLinea.add(linea);
  registrar("linea", formaLinea);

  // `o`: el hueco de hablar; su escala en Y es la apertura.
  const formaO = new THREE.Group();
  const hollow = new THREE.Mesh(new THREE.SphereGeometry(0.19, 24, 18), flat(PALETTE.lavender));
  hollow.scale.set(1, 0.92, 0.42);
  formaO.add(hollow);
  const tongue = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), flat(PALETTE.pink));
  tongue.scale.set(1, 0.6, 0.5);
  tongue.position.set(0, -0.06, 0.06);
  formaO.add(tongue);
  formaO.position.y = -0.04;
  registrar("o", formaO);

  // `mueca`: la línea, pero torcida y corta. Duda y disgusto.
  const formaMueca = new THREE.Group();
  const mueca = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.028, 0.17, 4, 8),
    flat(PALETTE.lavender),
  );
  mueca.rotation.z = Math.PI / 2 + 0.34;
  mueca.scale.z = 0.5;
  mueca.position.x = 0.03;
  formaMueca.add(mueca);
  registrar("mueca", formaMueca);

  const makeWhiskers = (): THREE.Group => {
    const group = new THREE.Group();
    const geometry = new THREE.CylinderGeometry(0.018, 0.007, 1, 6);
    const layout = [
      { length: 1.05, y: 0.14, tilt: 0.32 },
      { length: 1.15, y: 0, tilt: 0.06 },
      { length: 1, y: -0.15, tilt: -0.26 },
    ];
    for (const { length, y, tilt } of layout) {
      const pivot = new THREE.Group();
      pivot.position.y = y;
      pivot.rotation.z = tilt;
      const hair = new THREE.Mesh(geometry, flat(PALETTE.border));
      hair.scale.y = length;
      hair.rotation.z = Math.PI / 2; // el cilindro pasa a tumbarse sobre X
      hair.position.x = -length / 2; // crece hacia -X desde el pivote
      pivot.add(hair);
      group.add(pivot);
    }
    return group;
  };
  const whiskersLeft = makeWhiskers();
  whiskersLeft.position.set(-0.78, -0.22, 0.95);
  whiskersLeft.rotation.y = -0.55;
  cat.add(whiskersLeft);

  const whiskersRight = makeWhiskers();
  whiskersRight.position.set(0.78, -0.22, 0.95);
  whiskersRight.rotation.y = 0.55;
  whiskersRight.scale.x = -1; // espejo
  cat.add(whiskersRight);

  const spark = new THREE.Mesh(new THREE.OctahedronGeometry(0.19), flat(PALETTE.lavender));
  spark.scale.set(0.5, 1, 0.5);
  spark.position.set(0, 1.16, 0.66);
  cat.add(spark);

  // puntos de pensar y anillo de escucha viven fuera de `cat`: no flotan con ella
  const dots = new THREE.Group();
  const dotBaseY: number[] = [];
  for (const [x, y, r] of [
    [1.55, 0.8, 0.06],
    [1.88, 1.12, 0.08],
    [2.24, 1.5, 0.1],
  ]) {
    const dot = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12), flat(PALETTE.lavender, 0));
    dot.position.set(x, y, 0.2);
    dotBaseY.push(y);
    dots.add(dot);
  }
  scene.add(dots);

  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(1.95, 0.022, 8, 96),
    flat(PALETTE.lavender, 0),
  );
  ring.position.z = -0.2;
  scene.add(ring);

  // --- estado y vida propia -------------------------------------------------
  const current: Pose = { ...POSES.idle };
  let state: FaceState = "idle";

  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  let calm = motionQuery.matches;
  const onMotionChange = (event: MediaQueryListEvent) => {
    calm = event.matches;
  };
  motionQuery.addEventListener("change", onMotionChange);

  const claves = Object.keys(POSES.idle) as (keyof Pose)[];
  // Un muelle por propiedad de la pose. Solo el companion los usa; la PWA se
  // queda con la interpolación plana de siempre.
  const muelles = vivo
    ? (Object.fromEntries(
        claves.map((key) => [key, crearMuelle(POSES.idle[key])]),
      ) as Record<keyof Pose, Muelle>)
    : null;
  const cabezaY = crearMuelle(0);
  const punteroX = crearMuelle(0);
  const punteroY = crearMuelle(0);
  const puntero = crearSeguimientoPuntero();
  // Un peso por forma de boca. La de reposo arranca puesta para que el primer
  // fotograma tenga cara y no una boca a medio aparecer.
  const pesosBoca = Object.fromEntries(
    FORMAS.map((nombre) => [nombre, crearMuelle(nombre === "w" ? 1 : 0)]),
  ) as Record<FormaBoca, Muelle>;

  // El parpadeo se mide en tiempo desde que empezó, no como un valor que sube:
  // así el segundo ojo puede ir unas centésimas por detrás y el guiño sale
  // asimétrico, que es como parpadea una cara de verdad.
  let blinkT = 1;
  let desfaseOjo = 0;
  let untilBlink = 2.5;
  let dobleParpadeo = false;
  let gaze = { x: 0, y: 0 };
  let gazeHold = 0;
  let untilGaze = 4.8;
  let earFlick = 0;
  let untilFlick = 6;
  let untilEstiramiento = 22 + Math.random() * 14;
  let estiramiento = 0;
  // Las cejas nunca están del todo quietas. Es el gesto más barato que existe
  // y el que más delata que hay alguien detrás de la cara.
  let cejaTic = 0;
  let untilCeja = 4 + Math.random() * 5;

  const frame = (time: number, delta: number) => {
    const target = POSES[state];
    if (muelles && !calm) {
      for (const key of claves) {
        current[key] = avanzarMuelle(
          muelles[key],
          target[key],
          delta,
          RIGIDEZ,
          ELASTICAS.has(key) ? AMORTIGUACION_ELASTICA : AMORTIGUACION_FIRME,
        );
      }
    } else if (muelles) {
      for (const key of claves) current[key] = fijarMuelle(muelles[key], target[key]);
    } else {
      const k = calm ? 1 : Math.min(1, delta * 5);
      for (const key of claves) {
        current[key] = lerp(current[key], target[key], k);
      }
    }

    let bob = 0;
    let bounce = 0;
    let whiskerTwitch = 0;
    let mouthOpen = 1;
    let mirando: { x: number; y: number } | null = null;

    if (!calm) {
      // Un seno puro se oye como bucle a los pocos segundos. El segundo
      // armónico, en una frecuencia que no es múltiplo del primero, hace que la
      // respiración tarde mucho más en repetirse igual.
      bob = vivo
        ? (Math.sin(time * current.bobSpeed) * 0.78 +
            Math.sin(time * current.bobSpeed * 0.47 + 1.1) * 0.22) *
          current.bobAmp
        : Math.sin(time * current.bobSpeed) * current.bobAmp;
      if (state === "speaking") bounce = Math.abs(Math.sin(time * 5.2)) * 0.035;

      mirando = vivo ? puntero.avanzar(delta) : null;

      if (state !== "offline") {
        untilBlink -= delta;
        if (untilBlink <= 0) {
          // Los gatos encadenan dos parpadeos a menudo; el segundo llega tan
          // pegado que se lee como un tic, no como otro parpadeo.
          if (dobleParpadeo) {
            untilBlink = 0.16;
            dobleParpadeo = false;
          } else {
            untilBlink = 3 + Math.random() * 3;
            dobleParpadeo = vivo && Math.random() < 0.32;
          }
          desfaseOjo = vivo && Math.random() < 0.25 ? 0.045 : 0;
          blinkT = 0;
        }
        blinkT += delta;
      } else {
        blinkT = 1;
      }

      if (state === "idle" && !mirando) {
        untilGaze -= delta;
        if (untilGaze <= 0) {
          untilGaze = 3.5 + Math.random() * 3;
          gaze = { x: (Math.random() - 0.5) * 0.09, y: (Math.random() - 0.5) * 0.04 };
          gazeHold = 1.1;
        }
        gazeHold -= delta;
        if (gazeHold <= 0) gaze = { x: 0, y: 0 };

        // flick de oreja aleatorio, gesto gato 100%
        untilFlick -= delta;
        if (untilFlick <= 0) {
          untilFlick = 5 + Math.random() * 5;
          earFlick = 1;
        }
      } else {
        gaze = { x: 0, y: 0 };
      }
      earFlick = Math.max(0, earFlick - delta * 3.2);

      // Estiramiento: el gesto largo que delata que hay alguien esperando y no
      // un salvapantallas. Solo en reposo y solo si nadie la está mirando.
      if (vivo && state === "idle" && !mirando) {
        untilEstiramiento -= delta;
        if (untilEstiramiento <= 0) {
          untilEstiramiento = 25 + Math.random() * 15;
          estiramiento = 1;
        }
      }
      // El gesto en curso termina aunque cambie el estado: cortarlo a medias
      // deja la cabeza y las orejas pegando un salto.
      if (estiramiento > 0) estiramiento = Math.max(0, estiramiento - delta / 1.7);

      if (vivo) {
        untilCeja -= delta;
        if (untilCeja <= 0) {
          untilCeja = 3.5 + Math.random() * 6;
          cejaTic = 1;
        }
        cejaTic = Math.max(0, cejaTic - delta * 1.6);
      }

      if (state === "speaking") {
        mouthOpen = 0.32 + (Math.sin(time * 12) * 0.5 + 0.5) * 0.68;
        whiskerTwitch = Math.sin(time * 6.5) * 0.09;
      }

      spark.rotation.y = time * 1.1;
      spark.rotation.z = Math.sin(time * 1.6) * 0.35;
      const sparkScale = 0.85 + Math.sin(time * (state === "listening" ? 4.2 : 1.7)) * 0.25;
      spark.scale.set(0.5 * sparkScale, sparkScale, 0.5 * sparkScale);
    }

    // El estiramiento va montado encima de la pose, no en su lugar: alarga el
    // cuello, echa las orejas atrás y cierra los ojos a medias.
    const arco = pulso(1 - estiramiento);

    if (vivo) {
      const objetivoX = mirando ? acotar(mirando.x, -1, 1) : 0;
      const objetivoY = mirando ? acotar(mirando.y, -1, 1) : 0;
      const suave = calm ? 0 : 1;
      avanzarMuelle(punteroX, objetivoX * suave, delta, 90, 17);
      avanzarMuelle(punteroY, objetivoY * suave, delta, 90, 17);
      // La cabeza acompaña una fracción de lo que hacen los ojos: girarla del
      // todo la saca de encuadre y rompe el contorno del cel-shading.
      avanzarMuelle(cabezaY, punteroX.valor * 0.2, delta, 90, 17);
    }

    cat.position.y = bob + bounce + arco * 0.06;
    cat.rotation.z = current.headZ + (calm ? 0 : Math.sin(time * 0.7) * 0.012);
    cat.rotation.x = current.headX + punteroY.valor * 0.07 - arco * 0.09;
    cat.rotation.y = cabezaY.valor;

    earLeft.rotation.z = -0.3 + current.ears + earFlick * -0.5 - arco * 0.26;
    earRight.rotation.z = 0.3 - current.ears + arco * 0.26;

    const happyEyes = current.happy > 0.5;
    // Cuánto ha avanzado el parpadeo en cada ojo. 0 es cerrado del todo.
    const avanceParpadeo = (retardo: number) =>
      acotar((blinkT - retardo) * 9, 0, 1);

    for (const [indice, { eye, inner, pupil, lidTop, lidBottom }] of [
      eyeLeft,
      eyeRight,
    ].entries()) {
      const abierto = avanceParpadeo(indice === 1 ? desfaseOjo : 0);
      eye.visible = !happyEyes;
      eye.scale.set(current.eyeX, Math.max(0.02, current.eyeY), 1);
      inner.position.x = current.gazeX + gaze.x + punteroX.valor * 0.075;
      inner.position.y = current.gazeY + gaze.y - punteroY.valor * 0.05;

      // El de arriba hace casi todo el trabajo y el de abajo acompaña: cerrar
      // los dos a partes iguales da un ojo que se aplasta, no que se cierra.
      const cierreSup = acotar(
        current.lidTop + (1 - abierto) * 0.95 + arco * 0.7,
        0,
        1,
      );
      const cierreInf = acotar(
        current.lidBottom + (1 - abierto) * 0.25 + arco * 0.2,
        0,
        1,
      );
      lidTop.position.y = lerp(0.56, 0, cierreSup);
      lidBottom.position.y = lerp(-0.56, -0.02, cierreInf);

      const dilatacion = acotar(current.pupil, 0.4, 1.8);
      pupil.scale.set(dilatacion, dilatacion * 1.15, 0.4);
    }
    arcLeft.visible = happyEyes;
    arcRight.visible = happyEyes;

    for (const [indice, ceja] of [browLeft, browRight].entries()) {
      const dentro = indice === 0 ? 1 : -1;
      ceja.position.y =
        0.62 + current.browY + (calm ? 0 : pulso(1 - cejaTic) * 0.055);
      ceja.rotation.z = current.browTilt * dentro;
    }

    (blushLeft.material as THREE.MeshBasicMaterial).opacity = acotar(current.blush, 0, 1);
    (blushRight.material as THREE.MeshBasicMaterial).opacity = acotar(current.blush, 0, 1);

    // Las bocas se cruzan por peso: la que toca crece y se opaca mientras la
    // anterior se encoge, así que no hay ningún fotograma sin boca.
    const objetivo = BOCA[state];
    for (const nombre of FORMAS) {
      const peso = acotar(
        calm
          ? fijarMuelle(pesosBoca[nombre], nombre === objetivo ? 1 : 0)
          : avanzarMuelle(
              pesosBoca[nombre],
              nombre === objetivo ? 1 : 0,
              delta,
              RIGIDEZ,
              AMORTIGUACION_FIRME,
            ),
        0,
        1,
      );
      const grupo = shapes[nombre];
      grupo.visible = peso > 0.02;
      if (!grupo.visible) continue;
      const escala = 0.55 + peso * 0.45;
      grupo.scale.set(escala, escala * (nombre === "o" ? mouthOpen : 1), escala);
      grupo.traverse((objeto) => {
        if (objeto instanceof THREE.Mesh) {
          (objeto.material as THREE.MeshBasicMaterial).opacity = peso;
        }
      });
    }
    // Dudar tuerce la boca hacia un lado, como en la versión SVG.
    mouth.rotation.z = current.dots * -0.16;
    mouth.position.x = current.dots * 0.04;

    whiskersLeft.rotation.z = whiskerTwitch + current.dots * -0.08;
    whiskersRight.rotation.z = -whiskerTwitch + current.dots * 0.08;

    const fuerzaDots = acotar(current.dots, 0, 1);
    dots.visible = fuerzaDots > 0.02;
    dots.children.forEach((dot, i) => {
      const wave = Math.sin(time * 4.6 - i * 0.7);
      const material = (dot as THREE.Mesh).material as THREE.MeshBasicMaterial;
      material.opacity = fuerzaDots * (calm ? 0.8 : 0.35 + (wave * 0.5 + 0.5) * 0.65);
      dot.position.y = dotBaseY[i] + (calm ? 0 : wave * 0.13);
    });

    const fuerzaRing = acotar(current.ring, 0, 1);
    ring.visible = fuerzaRing > 0.02;
    if (ring.visible) {
      const phase = calm ? 0.3 : (time * 0.72) % 1;
      ring.scale.setScalar(0.9 + phase * 0.26);
      (ring.material as THREE.MeshBasicMaterial).opacity = fuerzaRing * (1 - phase) * 0.6;
    }
  };

  const ritmo = crearRitmo(60, 30);
  let previous = 0;
  let pendiente = 0;
  renderer.setAnimationLoop((ms) => {
    const time = ms / 1000;
    const delta = Math.min(0.05, time - previous);
    previous = time;
    // La ventana del companion se esconde entre conversación y conversación.
    // Mientras está oculta no hay nada que dibujar, y el navegador no siempre
    // frena el bucle por su cuenta.
    if (typeof document !== "undefined" && document.hidden) return;
    pendiente += delta;
    // Quieta y sin nadie encima, media cadencia basta. El delta acumulado va
    // aparte del reparto de fotogramas, así que bajar a 30 no ralentiza nada:
    // los gestos siguen durando lo mismo, solo se dibujan menos veces.
    const activo = state !== "idle" || puntero.activo || estiramiento > 0;
    if (vivo && !ritmo.debeDibujar(time, activo)) return;
    frame(time, Math.min(0.05, pendiente));
    pendiente = 0;
    renderer.render(scene, camera);
  });

  const resize = () => {
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (!width || !height) return;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
  };
  resize();

  return {
    setState(next: FaceState) {
      if (!POSES[next] || next === state) return;
      state = next;
      // Pensando mira a sus puntos suspensivos, no a ti. En los demás estados
      // el seguimiento sigue vivo: que te mire mientras te escucha es
      // justamente el gesto que hace que parezca que hay alguien.
      if (next === "thinking") puntero.soltar();
    },
    setPointer(x: number, y: number) {
      if (vivo) puntero.apuntar(x, y);
    },
    clearPointer() {
      puntero.soltar();
    },
    resize,
    dispose() {
      renderer.setAnimationLoop(null);
      motionQuery.removeEventListener("change", onMotionChange);
      scene.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        object.geometry.dispose();
        const material = object.material;
        if (Array.isArray(material)) material.forEach((entry) => entry.dispose());
        else material.dispose();
      });
      toonRamp.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
