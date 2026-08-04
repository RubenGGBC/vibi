import * as THREE from "three";

/**
 * La cara de Morgana en 3D.
 *
 * El módulo no sabe nada de React: recibe un contenedor, monta una escena de
 * Three.js dentro y expone `setState`, `resize` y `dispose`. Así la lógica de
 * voz de `FacePanel` no se mezcla con WebGL y esto se puede probar aparte.
 */

export type FaceState = "idle" | "listening" | "thinking" | "speaking";

export interface FaceScene {
  setState(state: FaceState): void;
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
};

interface Pose {
  headZ: number;
  headX: number;
  ears: number;
  eyeX: number;
  eyeY: number;
  gazeX: number;
  gazeY: number;
  blush: number;
  happy: number;
  talking: number;
  dots: number;
  ring: number;
  bobAmp: number;
  bobSpeed: number;
}

const POSES: Record<FaceState, Pose> = {
  idle: {
    headZ: 0, headX: 0, ears: 0, eyeX: 1, eyeY: 1,
    gazeX: 0, gazeY: 0, blush: 0, happy: 0, talking: 0,
    dots: 0, ring: 0, bobAmp: 0.09, bobSpeed: 1.2,
  },
  listening: {
    headZ: 0.1, headX: 0.02, ears: 0.26, eyeX: 1.18, eyeY: 1.2,
    gazeX: 0, gazeY: 0.01, blush: 0.4, happy: 0, talking: 0,
    dots: 0, ring: 1, bobAmp: 0.05, bobSpeed: 1.9,
  },
  thinking: {
    headZ: -0.07, headX: -0.07, ears: -0.14, eyeX: 1, eyeY: 0.5,
    gazeX: 0.045, gazeY: 0.05, blush: 0, happy: 0, talking: 0,
    dots: 1, ring: 0, bobAmp: 0.05, bobSpeed: 0.75,
  },
  speaking: {
    headZ: 0, headX: 0.03, ears: 0.1, eyeX: 1, eyeY: 1,
    gazeX: 0, gazeY: 0, blush: 0.6, happy: 1, talking: 1,
    dots: 0, ring: 0, bobAmp: 0.11, bobSpeed: 5.2,
  },
};

export function supportsWebGL(): boolean {
  try {
    const probe = document.createElement("canvas");
    return Boolean(probe.getContext("webgl2") ?? probe.getContext("webgl"));
  } catch {
    return false;
  }
}

const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

export function createFaceScene(container: HTMLElement): FaceScene | null {
  if (!supportsWebGL()) return null;

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

  // ojos: grandes y con doble brillo, igual que en la versión SVG
  const makeEye = (side: number) => {
    const eye = new THREE.Group(); // escala -> parpadeo y entrecerrar
    eye.position.set(0.52 * side, 0.16, 1.1);
    eye.rotation.y = 0.34 * side;

    const inner = new THREE.Group(); // posición -> mirada
    eye.add(inner);

    const globe = new THREE.Mesh(new THREE.SphereGeometry(0.23, 32, 24), flat(PALETTE.lavender));
    globe.scale.set(1, 1.24, 0.5);
    inner.add(globe);

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

    cat.add(eye);
    return { eye, inner };
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

  // boca w en reposo: dos arcos que se tocan en el centro
  const restingMouth = new THREE.Group();
  for (const side of [-1, 1]) {
    const curve = new THREE.Mesh(
      new THREE.TorusGeometry(0.11, 0.028, 8, 20, Math.PI),
      flat(PALETTE.lavender),
    );
    curve.rotation.z = Math.PI;
    curve.position.x = 0.11 * side;
    restingMouth.add(curve);
  }
  restingMouth.position.set(0, -0.42, 1.34);
  cat.add(restingMouth);

  const speakingMouth = new THREE.Group();
  const mouthHollow = new THREE.Mesh(new THREE.SphereGeometry(0.19, 24, 18), flat(PALETTE.lavender));
  mouthHollow.scale.set(1, 0.92, 0.42);
  speakingMouth.add(mouthHollow);
  const tongue = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), flat(PALETTE.pink));
  tongue.scale.set(1, 0.6, 0.5);
  tongue.position.set(0, -0.06, 0.06);
  speakingMouth.add(tongue);
  speakingMouth.position.set(0, -0.47, 1.26);
  speakingMouth.visible = false;
  cat.add(speakingMouth);

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

  let blink = 1;
  let untilBlink = 2.5;
  let gaze = { x: 0, y: 0 };
  let gazeHold = 0;
  let untilGaze = 4.8;
  let earFlick = 0;
  let untilFlick = 6;

  const frame = (time: number, delta: number) => {
    const target = POSES[state];
    const k = calm ? 1 : Math.min(1, delta * 5);
    for (const key of Object.keys(target) as (keyof Pose)[]) {
      current[key] = lerp(current[key], target[key], k);
    }

    let bob = 0;
    let bounce = 0;
    let whiskerTwitch = 0;
    let mouthOpen = 1;

    if (!calm) {
      bob = Math.sin(time * current.bobSpeed) * current.bobAmp;
      if (state === "speaking") bounce = Math.abs(Math.sin(time * 5.2)) * 0.035;

      if (state === "idle" || state === "listening") {
        untilBlink -= delta;
        if (untilBlink <= 0) {
          untilBlink = 3 + Math.random() * 3;
          blink = 0;
        }
        blink = Math.min(1, blink + delta * 9);
      } else {
        blink = 1;
      }

      if (state === "idle") {
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

      if (state === "speaking") {
        mouthOpen = 0.32 + (Math.sin(time * 12) * 0.5 + 0.5) * 0.68;
        whiskerTwitch = Math.sin(time * 6.5) * 0.09;
      }

      spark.rotation.y = time * 1.1;
      spark.rotation.z = Math.sin(time * 1.6) * 0.35;
      const sparkScale = 0.85 + Math.sin(time * (state === "listening" ? 4.2 : 1.7)) * 0.25;
      spark.scale.set(0.5 * sparkScale, sparkScale, 0.5 * sparkScale);
    }

    cat.position.y = bob + bounce;
    cat.rotation.z = current.headZ + (calm ? 0 : Math.sin(time * 0.7) * 0.012);
    cat.rotation.x = current.headX;

    earLeft.rotation.z = -0.3 + current.ears + earFlick * -0.5;
    earRight.rotation.z = 0.3 - current.ears;

    const happyEyes = current.happy > 0.5;
    for (const { eye, inner } of [eyeLeft, eyeRight]) {
      eye.visible = !happyEyes;
      eye.scale.set(current.eyeX, current.eyeY * blink, 1);
      inner.position.x = current.gazeX + gaze.x;
      inner.position.y = current.gazeY + gaze.y;
    }
    arcLeft.visible = happyEyes;
    arcRight.visible = happyEyes;

    (blushLeft.material as THREE.MeshBasicMaterial).opacity = current.blush;
    (blushRight.material as THREE.MeshBasicMaterial).opacity = current.blush;

    const talking = current.talking > 0.5;
    restingMouth.visible = !talking;
    speakingMouth.visible = talking;
    speakingMouth.scale.set(1, mouthOpen, 1);
    // en thinking la boca se tuerce, igual que en la versión SVG
    restingMouth.rotation.z = current.dots * -0.22;
    restingMouth.position.x = current.dots * 0.05;

    whiskersLeft.rotation.z = whiskerTwitch + current.dots * -0.08;
    whiskersRight.rotation.z = -whiskerTwitch + current.dots * 0.08;

    dots.visible = current.dots > 0.02;
    dots.children.forEach((dot, i) => {
      const wave = Math.sin(time * 4.6 - i * 0.7);
      const material = (dot as THREE.Mesh).material as THREE.MeshBasicMaterial;
      material.opacity = current.dots * (calm ? 0.8 : 0.35 + (wave * 0.5 + 0.5) * 0.65);
      dot.position.y = dotBaseY[i] + (calm ? 0 : wave * 0.13);
    });

    ring.visible = current.ring > 0.02;
    if (ring.visible) {
      const phase = calm ? 0.3 : (time * 0.72) % 1;
      ring.scale.setScalar(0.9 + phase * 0.26);
      (ring.material as THREE.MeshBasicMaterial).opacity = current.ring * (1 - phase) * 0.6;
    }
  };

  let previous = 0;
  renderer.setAnimationLoop((ms) => {
    const time = ms / 1000;
    const delta = Math.min(0.05, time - previous);
    previous = time;
    frame(time, delta);
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
      if (POSES[next]) state = next;
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
