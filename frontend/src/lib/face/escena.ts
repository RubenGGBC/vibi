import { crearAntena, ANTENA_REPOSO, type EstadoAntena } from "./antena";
import { BotEngine, type BotFrame, type Look } from "./bloub/engine";
import { EXPRESSION_BY_ID } from "./bloub/expressions";
import { DEMI_VIEWBOX, RAYON } from "./bloub/repere";
import type { FacePerfil, FaceState } from "./estados";
import { SENALES_QUIETAS, ajustesDe, type Senales } from "./modificadores";
import { crearLiquido } from "./liquido";
import { nivelDeVoz } from "./oido";
import { crearOjos } from "./ojos";
import { cuerpoDe, interpretar } from "./puente";
import { DURACION_SACADA, crearSacadas } from "./sacadas";

/**
 * La cara de Vibi, montada en SVG.
 *
 * La geometría y el movimiento son de `bloub/` y no se tocan: esta capa solo
 * traduce sus fotogramas a nodos, y le añade lo que es de Vibi y el referente
 * no tiene —la antena y las señales vivas del turno—.
 *
 * El modelo de dibujo es el suyo y merece explicarse, porque no es el evidente:
 * **los ojos son agujeros perforados en el cuerpo** con una máscara, no formas
 * puestas encima. Por eso se recortan solos contra la silueta cuando resbalan
 * hacia el borde, en lugar de asomar por fuera. Debajo del cuerpo va un fondo
 * opaco con su misma forma; sin él, la mitad trasera de un anillo —que se
 * dibuja antes justo para quedar oculta— reaparecería DENTRO de los ojos.
 *
 * Se escriben atributos y no se vuelve a renderizar React: rerenderizar un
 * componente sesenta veces por segundo para mover una forma es trabajo tirado.
 */

/**
 * Cada cuánto se repinta la cara, en segundos entre fotogramas.
 *
 * El bucle iba a sesenta pasara lo que pasara, y en reposo eso no se sostiene:
 * medido en el companion el 18/08/2026, el proceso que dibuja se llevaba el 44%
 * de un núcleo —y el que compone, otro 34%— para una cara de 320 px en la que
 * lo único que se movía era el parpadeo y la deriva de la mirada. Ninguno de
 * los dos se nota a veinte por segundo.
 *
 * No se baja de ahí porque el parpadeo dura poco más de una décima: por debajo
 * se ve como un salto en vez de como un ojo cerrándose.
 *
 * En una pantalla de 60 Hz el reposo cae a un fotograma de cada tres, que son
 * veinte reales y no veinticuatro. Se deja el objetivo en veinticuatro para no
 * atarlo a la frecuencia del monitor: en uno de 120 Hz salen los veinticuatro.
 */
const CADENCIA_REPOSO = 1 / 24;
const CADENCIA_VIVA = 1 / 60;

/** Los estados en los que la cara no está contando nada. */
const QUIETOS: ReadonlySet<FaceState> = new Set<FaceState>(["idle", "offline"]);

/**
 * Cada cuántos segundos toca repintar.
 *
 * Seguir al cursor manda sobre el estado: ahí el movimiento es continuo y lo
 * está provocando el usuario, así que a veinte se vería a tirones.
 */
export function cadenciaDe(estado: FaceState, siguiendoPuntero: boolean): number {
  return siguiendoPuntero || !QUIETOS.has(estado) ? CADENCIA_VIVA : CADENCIA_REPOSO;
}

const NS = "http://www.w3.org/2000/svg";

let contador = 0;

export interface FaceScene {
  setState(state: FaceState): void;
  setSenales(senales: Senales): void;
  /** Adónde mira, de -1 a 1 sobre el contenedor. Solo en `companion`. */
  setPointer(x: number, y: number): void;
  clearPointer(): void;
  /** Pinta un fotograma. La usan el bucle y el montaje inicial. */
  dibujar(delta: number): void;
  resize(): void;
  dispose(): void;
}

export interface OpcionesEscena {
  perfil?: FacePerfil;
}

const crear = <K extends keyof SVGElementTagNameMap>(
  tag: K,
  clase?: string,
): SVGElementTagNameMap[K] => {
  const nodo = document.createElementNS(NS, tag);
  if (clase) nodo.setAttribute("class", clase);
  return nodo;
};

/** Reserva nodos según hagan falta y esconde los que sobran. */
function grupoElastico<K extends keyof SVGElementTagNameMap>(
  padre: SVGElement,
  tag: K,
  clase: string,
) {
  const nodos: SVGElementTagNameMap[K][] = [];
  return {
    ajustar(cuantos: number): SVGElementTagNameMap[K][] {
      while (nodos.length < cuantos) {
        const nodo = crear(tag, clase);
        padre.appendChild(nodo);
        nodos.push(nodo);
      }
      for (let i = cuantos; i < nodos.length; i += 1) {
        nodos[i].setAttribute("opacity", "0");
      }
      return nodos.slice(0, cuantos);
    },
  };
}

export function crearEscenaCara(
  contenedor: HTMLElement,
  opciones: OpcionesEscena = {},
): FaceScene {
  const { perfil = "web" } = opciones;
  const uid = `vibi-${(contador += 1)}`;
  const V = DEMI_VIEWBOX;

  const svg = crear("svg", "vibi-svg");
  svg.setAttribute("viewBox", `${-V} ${-V} ${V * 2} ${V * 2}`);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

  const defs = crear("defs");
  const mascara = crear("mask");
  mascara.setAttribute("id", `${uid}-m`);
  mascara.setAttribute("maskUnits", "userSpaceOnUse");
  mascara.setAttribute("x", String(-V));
  mascara.setAttribute("y", String(-V));
  mascara.setAttribute("width", String(V * 2));
  mascara.setAttribute("height", String(V * 2));
  // Blanco deja ver, negro tapa: el cuerpo entero menos los ojos y la muesca.
  const mCuerpo = crear("path");
  mCuerpo.setAttribute("fill", "#fff");
  mascara.appendChild(mCuerpo);
  const mOjos = grupoElastico(mascara, "path", "");
  const mMuesca = crear("circle");
  mMuesca.setAttribute("fill", "#000");
  mascara.appendChild(mMuesca);
  defs.appendChild(mascara);
  svg.appendChild(defs);

  // La antena va detrás de todo: el tallo tiene que salir de dentro de la
  // cabeza, no quedar pegado encima.
  const gAntena = crear("g", "vibi-antena");
  const tallo = crear("path", "vibi-tallo");
  tallo.setAttribute("fill", "none");
  tallo.setAttribute("stroke", "var(--vibi-tallo, #7d7490)");
  tallo.setAttribute("stroke-linecap", "round");
  const bola = crear("circle", "vibi-bola");
  bola.setAttribute("fill", "var(--vibi-bola, rgb(181 126 255))");
  gAntena.append(tallo, bola);

  const gArcosDetras = crear("g", "vibi-arcos-detras");
  gArcosDetras.setAttribute("fill", "none");
  gArcosDetras.setAttribute("stroke-linecap", "round");
  const gPuntosDetras = crear("g", "vibi-puntos-detras");

  const gCuerpo = crear("g", "vibi-cuerpo");
  const fondo = crear("path", "vibi-fondo");
  fondo.setAttribute("fill", "var(--vibi-fondo, #171321)");
  const tinta = crear("g");
  tinta.setAttribute("mask", `url(#${uid}-m)`);
  const relleno = crear("rect");
  relleno.setAttribute("x", String(-V));
  relleno.setAttribute("y", String(-V));
  relleno.setAttribute("width", String(V * 2));
  relleno.setAttribute("height", String(V * 2));
  relleno.setAttribute("fill", "var(--vibi-tinta, #cdc4f0)");
  tinta.appendChild(relleno);
  gCuerpo.append(fondo, tinta);

  const gPuntos = crear("g", "vibi-puntos");
  const insignia = crear("circle", "vibi-insignia");
  insignia.setAttribute("fill", "var(--vibi-insignia, #d89cff)");
  const gArcosDelante = crear("g", "vibi-arcos-delante");
  gArcosDelante.setAttribute("fill", "none");
  gArcosDelante.setAttribute("stroke-linecap", "round");

  svg.append(gAntena, gArcosDetras, gPuntosDetras, gCuerpo, gPuntos, insignia, gArcosDelante);
  contenedor.appendChild(svg);

  const arcosDetras = grupoElastico(gArcosDetras, "path", "vibi-arco");
  const arcosDelante = grupoElastico(gArcosDelante, "path", "vibi-arco");
  const puntosDetras = grupoElastico(gPuntosDetras, "circle", "vibi-punto");
  const puntos = grupoElastico(gPuntos, "circle", "vibi-punto");
  const degradados = grupoElastico(defs, "linearGradient", "");

  const motor = new BotEngine(RAYON);
  const antena = crearAntena();
  const liquido = crearLiquido();
  const ojos = crearOjos();
  const sacadas = crearSacadas();

  let vivo = true;
  let pedido = 0;
  let ultimaMarca = 0;
  let reloj = 0;
  let estado: FaceState = "idle";
  let senales: Senales = SENALES_QUIETAS;
  let puntero: { x: number; y: number } | null = null;
  let asentada = false;

  const aplicar = (nuevo: FaceState, ahora: number) => {
    const plan = interpretar(nuevo);
    motor.setState(plan.base, ahora);
    motor.setExpression(plan.expresion ? EXPRESSION_BY_ID.get(plan.expresion) ?? null : null, ahora);
    // Al cambiar de gesto, la mirada salta ya en el fotograma siguiente en vez
    // de esperar a que venza la espera del gesto anterior.
    sacadas.reiniciar();
  };

  const dibujarPuntos = (
    grupo: ReturnType<typeof grupoElastico<"circle">>,
    lista: BotFrame["dots"],
  ) => {
    grupo.ajustar(lista.length).forEach((nodo, i) => {
      const d = lista[i];
      nodo.setAttribute("cx", d.x.toFixed(2));
      nodo.setAttribute("cy", d.y.toFixed(2));
      nodo.setAttribute("r", (d.r ?? 0).toFixed(2));
      nodo.setAttribute("opacity", (d.opacity ?? 1).toFixed(3));
      nodo.setAttribute("fill", d.color ?? "var(--vibi-tinta, #cdc4f0)");
    });
  };

  const pintar = (marco: BotFrame, ahora: number, delta: number) => {
    mCuerpo.setAttribute("d", marco.bodyPath);
    fondo.setAttribute("d", marco.bodyPath);
    gCuerpo.setAttribute("opacity", marco.bodyAlpha.toFixed(3));

    // La matriz es del motor —dónde se posa el ojo sobre la esfera y con qué
    // escorzo, que es lo medido— y el trazado es de Vibi. En el SVG eso es
    // literalmente cambiar el `d` de cada agujero y no tocar nada más.
    const plan = interpretar(estado);
    const trazos = ojos.trazar(plan.ojo, plan.ojoDer ?? plan.ojo, delta);
    mOjos.ajustar(marco.eyes.length).forEach((nodo, i) => {
      const ojo = marco.eyes[i];
      nodo.setAttribute("d", trazos[i] ?? ojo.d);
      nodo.setAttribute("transform", ojo.matrix);
      nodo.setAttribute("opacity", ojo.alpha.toFixed(3));
      nodo.setAttribute("fill", "#000");
    });

    if (marco.notch) {
      mMuesca.setAttribute("cx", marco.notch.x.toFixed(2));
      mMuesca.setAttribute("cy", marco.notch.y.toFixed(2));
      mMuesca.setAttribute("r", marco.notch.r.toFixed(2));
    } else {
      mMuesca.setAttribute("r", "0");
    }

    if (marco.notif) {
      insignia.setAttribute("cx", marco.notif.x.toFixed(2));
      insignia.setAttribute("cy", marco.notif.y.toFixed(2));
      insignia.setAttribute("r", marco.notif.r.toFixed(2));
      insignia.setAttribute("opacity", "1");
    } else {
      insignia.setAttribute("opacity", "0");
    }

    dibujarPuntos(marco.dotsBehind ? puntosDetras : puntos, marco.dots);
    if (marco.dotsBehind) puntos.ajustar(0);
    else puntosDetras.ajustar(0);

    const grads = degradados.ajustar(marco.arcs.length);
    const detras = arcosDetras.ajustar(marco.arcs.length);
    const delante = arcosDelante.ajustar(marco.arcs.length);
    marco.arcs.forEach((arco, i) => {
      const g = grads[i];
      const id = `${uid}-g${i}`;
      g.setAttribute("id", id);
      g.setAttribute("gradientUnits", "userSpaceOnUse");
      g.setAttribute("x1", String(arco.grad.x1));
      g.setAttribute("y1", String(arco.grad.y1));
      g.setAttribute("x2", String(arco.grad.x2));
      g.setAttribute("y2", String(arco.grad.y2));
      while (g.firstChild) g.removeChild(g.firstChild);
      arco.grad.stops.forEach((color, k) => {
        const parada = crear("stop");
        parada.setAttribute("offset", String(k / Math.max(1, arco.grad.stops.length - 1)));
        parada.setAttribute("stop-color", color);
        g.appendChild(parada);
      });
      for (const [nodo, d] of [
        [detras[i], arco.back],
        [delante[i], arco.front],
      ] as const) {
        nodo.setAttribute("d", d);
        nodo.setAttribute("stroke", `url(#${id})`);
        nodo.setAttribute("stroke-width", String(arco.width));
        nodo.setAttribute("opacity", arco.opacity.toFixed(3));
      }
    });

    // La antena cuelga de lo alto del cuerpo y va por detrás. Su física corre
    // en unidades de cabeza y se escala aquí, como todo lo demás.
    const ajustes = ajustesDe(senales, Date.now());
    const estadoAntena: EstadoAntena = {
      ...ANTENA_REPOSO,
      radioBola: ANTENA_REPOSO.radioBola * ajustes.cargaBola,
      curva: ajustes.inclinacionRemota * 1.6,
    };
    const anclaje = { x: 0, y: -0.86 };
    const forma = asentada
      ? antena.avanzar(estadoAntena, anclaje, Math.min(1 / 30, ahora - reloj + 1 / 60))
      : antena.fijar(estadoAntena, anclaje);
    asentada = true;
    const e = (p: { x: number; y: number }) => ({ x: p.x * RAYON, y: p.y * RAYON });
    const b = e(forma.base);
    const c = e(forma.codo);
    const p = e(forma.bola);
    tallo.setAttribute("d", `M${b.x.toFixed(2)} ${b.y.toFixed(2)}Q${c.x.toFixed(2)} ${c.y.toFixed(2)} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`);
    tallo.setAttribute("stroke-width", (RAYON * 0.042).toFixed(2));
    bola.setAttribute("cx", p.x.toFixed(2));
    bola.setAttribute("cy", p.y.toFixed(2));
    bola.setAttribute("r", (forma.radioBola * RAYON).toFixed(2));
    // El brillo cae según se retrasa el pong: el aviso llega antes de que el
    // canal se declare caído.
    bola.setAttribute("opacity", (0.35 + ajustes.brilloBola * 0.65).toFixed(3));
  };

  const dibujar = (delta: number) => {
    if (!vivo) return;
    const ahora = reloj + delta;

    // El cursor manda sobre la mirada del gesto: si le prestas atención, te
    // mira. Sin cursor manda el gesto, y si tampoco tiene, su deriva libre.
    const plan = interpretar(estado);

    // El cuerpo líquido manda siempre: las tres siluetas dibujadas a mano —la
    // ventana, la hoja, la estirada— las sustituye ahora la elongación, que es
    // continua y no un salto entre dos trazados.
    motor.setShape(liquido.perfil(ahora, nivelDeVoz(), delta, cuerpoDe(estado)), ahora);

    // La mirada salta en vez de derivar. `setLook` solo se llama cuando hay
    // objetivo nuevo: llamarlo en cada fotograma reiniciaría la transición y el
    // ojo no llegaría nunca a ningún sitio.
    if (puntero && perfil === "companion") {
      // El cursor manda: si le prestas atención, te mira, y eso no es una
      // sacada sino un seguimiento.
      motor.setLook({ yaw: puntero.x, pitch: puntero.y, mix: 1, spin: 0, wander: 0.15 }, ahora);
    } else {
      const salto = sacadas.avanzar(plan.sacada, delta);
      if (salto) {
        motor.setLook(
          { yaw: salto.yaw / 30, pitch: salto.pitch / 30, mix: 1, spin: 0, wander: 0.05 },
          ahora,
          DURACION_SACADA,
        );
      }
    }

    pintar(motor.sample(ahora), ahora, delta);
    reloj = ahora;
  };

  const bucle = (marca: number) => {
    if (!vivo) return;
    pedido = requestAnimationFrame(bucle);
    const segundos = marca / 1000;
    const delta = ultimaMarca ? segundos - ultimaMarca : 1 / 60;
    // Se sale sin tocar `ultimaMarca`, y eso es lo que hace que bajar la
    // cadencia no ralentice nada: el tiempo saltado se acumula y lo hereda el
    // fotograma que sí se dibuja. El movimiento va con el reloj, no con la
    // cuenta de fotogramas.
    if (delta < cadenciaDe(estado, puntero !== null)) return;
    ultimaMarca = segundos;
    // Un salto grande —volver de una ventana minimizada— se recorta en vez de
    // recuperarse de golpe.
    dibujar(Math.min(delta, 0.05));
  };

  aplicar("idle", 0);
  // El primer fotograma va ya, sin esperar al bucle: si no, se ve el hueco.
  dibujar(1 / 60);
  pedido = requestAnimationFrame(bucle);

  return {
    setState(nuevo) {
      if (!vivo || nuevo === estado) return;
      estado = nuevo;
      aplicar(nuevo, reloj);
    },
    setSenales(nuevas) {
      if (vivo) senales = nuevas;
    },
    setPointer(x, y) {
      if (vivo && perfil === "companion") puntero = { x, y };
    },
    clearPointer() {
      puntero = null;
    },
    dibujar,
    // El `viewBox` deja el escalado en manos del navegador: no hay nada que
    // recalcular. Se conserva para no cambiarle el ciclo de vida a React.
    resize() {},
    dispose() {
      if (!vivo) return;
      vivo = false;
      cancelAnimationFrame(pedido);
      svg.remove();
    },
  };
}
