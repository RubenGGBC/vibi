import {
  acotar,
  avanzarMuelle,
  crearMuelle,
  crearSeguimientoPuntero,
  fijarMuelle,
  pulso,
  type Muelle,
} from "../faceMotion";
import type { FacePerfil, FaceState } from "./estados";
import { SENALES_QUIETAS, ajustesDe, type Senales } from "./modificadores";
import { nivelDeVoz } from "./oido";
import { crearSacadas } from "./sacadas";
import { PERFILADO, crearOjos, type FormaOjo } from "./vibi/formas";
import { gestoDe, type Complemento } from "./vibi/gestos";
import {
  ALA,
  ANTIFAZ,
  BOCA,
  CABEZA,
  COPA,
  GROSOR_BOCA,
  INTERROGACION,
  LENGUA,
  LENGUAS,
  LUPA,
  MARTILLO,
  OJOS,
  ONDA,
  PLIEGUES,
  VISTA,
} from "./vibi/rasgos";

/**
 * La cara de Vibi, montada en SVG.
 *
 * **Nada de esto son fotogramas grabados.** Es la diferencia que importa entre
 * esta cara y una lámina animada con `@keyframes`: cada atributo se calcula en
 * el instante en que se pinta, a partir de lo que está pasando de verdad —el
 * nivel del micrófono, el caudal de tokens, el retraso del canal, dónde tienes
 * el ratón—. Una animación grabada repetiría el mismo bucle pase lo que pase, y
 * eso es justo lo que hace que un personaje parezca un GIF y no alguien.
 *
 * Tres piezas cargan con casi todo el movimiento y ninguna se anima a mano:
 *
 * - **El sombrero persigue a la cabeza con un muelle**, no va pegado a ella.
 *   De ahí sale el movimiento secundario: la chistera llega tarde y se pasa de
 *   frenada, así que cualquier cabezazo la mueve gratis y ninguna pose tiene
 *   que acordarse de ella.
 * - **El cambio de estado es un empujón, no una transición.** `setState` le
 *   mete velocidad a un muelle que vuelve solo a cero; mientras vuelve, la
 *   cabeza se aplasta, se estira y se ladea. Por eso ningún par de estados
 *   necesita su propia animación de paso: hay treinta y dos estados y una sola
 *   transición, la que dicta la física.
 * - **Los ojos morfan punto a punto** (`vibi/formas.ts`), no se cambian de
 *   golpe ni se funden por opacidad.
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
 * lo único que se movía era el parpadeo.
 *
 * No se baja de veinticuatro porque el parpadeo dura poco más de una décima:
 * por debajo se ve como un salto en vez de como un ojo cerrándose.
 */
const CADENCIA_REPOSO = 1 / 24;
const CADENCIA_VIVA = 1 / 60;

/** Los estados en los que la cara no está contando nada. */
const QUIETOS: ReadonlySet<FaceState> = new Set<FaceState>(["idle", "offline", "vigilando"]);

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

const color = (variable: string, reserva: string) => `var(${variable}, ${reserva})`;

/** Dos senos que no comparten periodo: un meneo que no se repite a ojo. */
const meneo = (t: number, semilla: number): number =>
  Math.sin(t * 2.1 + semilla) * 0.62 + Math.sin(t * 3.73 + semilla * 2.3) * 0.38;

/**
 * Asomarse: entra, **se queda**, y se va.
 *
 * No sirve `pulso`, que sube y baja sin descanso: la interrogación solo estaría
 * del todo opaca un instante, y a media opacidad la sombra proyectada se le ve
 * por debajo y la apaga a granate. Lo que hace falta es que aguante.
 */
const asomo = (u: number): number => {
  const bruto = u < 0.18 ? u / 0.18 : u < 0.72 ? 1 : Math.max(0, 1 - (u - 0.72) / 0.28);
  return 0.5 - Math.cos(Math.PI * bruto) * 0.5;
};

/**
 * El ciclo del martillazo: 1 es el brazo cargado arriba, 0 el golpe.
 *
 * Sube despacio y baja de golpe, y ahí está todo. Una oscilación simétrica
 * —un seno— se lee como un péndulo o un limpiaparabrisas; lo que convierte
 * esto en un martillo es que las dos mitades duren distinto. El rebote del
 * final es lo que devuelve el yunque, y sin él el golpe parece amortiguado.
 */
const martillazo = (u: number): number => {
  if (u < 0.66) return 0.5 - Math.cos((Math.PI * u) / 0.66) * 0.5;
  if (u < 0.82) return 1 - (u - 0.66) / 0.16;
  return Math.sin(((u - 0.82) / 0.18) * Math.PI) * 0.12;
};

/** Suavizado exponencial: no depende de la cadencia, así que 24 y 60 fps llegan igual de rápido. */
const suavizar = (actual: number, destino: number, dt: number, tau: number): number =>
  actual + (destino - actual) * (1 - Math.exp(-dt / tau));

/** Escala y gira alrededor de un punto, y después traslada. */
const plantar = (
  dx: number,
  dy: number,
  giro: number,
  ex: number,
  ey: number,
  px: number,
  py: number,
): string =>
  `translate(${dx.toFixed(2)} ${dy.toFixed(2)}) translate(${px} ${py}) ` +
  `rotate(${giro.toFixed(2)}) scale(${ex.toFixed(4)} ${ey.toFixed(4)}) translate(${-px} ${-py})`;

/** Las formas que ya están cerradas: parpadear encima solo las haría temblar. */
const CERRADOS: ReadonlySet<FormaOjo> = new Set<FormaOjo>(["alegre", "sosiego"]);

/**
 * El parpadeo.
 *
 * Lo trae la cara y no el gesto: parpadear es de estar viva, no de estar
 * haciendo algo. Devuelve cuánto está abierto el ojo, de 1 a 0.
 */
function crearParpadeo(azar: () => number = Math.random) {
  const DURACION = 0.13;
  let espera = 1.4 + azar() * 3;
  let restante = 0;
  return {
    avanzar(dt: number): number {
      if (restante > 0) {
        restante -= dt;
        if (restante <= 0) {
          restante = 0;
          espera = 2.2 + azar() * 4;
          return 1;
        }
        return Math.abs(Math.cos((1 - restante / DURACION) * Math.PI));
      }
      espera -= dt;
      if (espera <= 0) restante = DURACION;
      return 1;
    },
  };
}

export function crearEscenaCara(
  contenedor: HTMLElement,
  opciones: OpcionesEscena = {},
): FaceScene {
  const { perfil = "web" } = opciones;
  const uid = `vibi-${(contador += 1)}`;

  const svg = crear("svg", "vibi-svg");
  svg.setAttribute("viewBox", `${VISTA.x} ${VISTA.y} ${VISTA.ancho} ${VISTA.alto}`);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

  // El antifaz se recorta contra la cabeza, así que puede desbordar sin cuidado:
  // lo único que se dibuja de él es por dónde pasa su borde de abajo.
  const defs = crear("defs");
  const recorte = crear("clipPath");
  recorte.setAttribute("id", `${uid}-c`);
  const recorteForma = crear("path");
  recorteForma.setAttribute("d", CABEZA);
  recorte.appendChild(recorteForma);
  defs.appendChild(recorte);
  svg.appendChild(defs);

  const figura = crear("g", "vibi-figura");
  const cuerpo = crear("g", "vibi-cuerpo");

  // La copa va detrás de la cara y el ala delante, pero las dos son el mismo
  // sombrero y llevan la misma matriz: por eso son dos grupos y no uno.
  const copa = crear("g", "vibi-copa");
  const copaForma = crear("path");
  copaForma.setAttribute("d", COPA);
  copaForma.setAttribute("fill", color("--vibi-rojo", "#f4121b"));
  copa.appendChild(copaForma);
  for (const pliegue of PLIEGUES) {
    const nodo = crear("path", "vibi-pliegue");
    nodo.setAttribute("d", pliegue.d);
    nodo.setAttribute("fill", "none");
    nodo.setAttribute("stroke", color("--vibi-rojo-hondo", "#a80a11"));
    nodo.setAttribute("stroke-width", String(pliegue.grosor));
    nodo.setAttribute("stroke-linecap", "round");
    copa.appendChild(nodo);
  }

  const carne = crear("path", "vibi-carne");
  carne.setAttribute("d", CABEZA);
  carne.setAttribute("fill", color("--vibi-carne", "#ffffff"));

  const recortado = crear("g");
  recortado.setAttribute("clip-path", `url(#${uid}-c)`);
  const antifaz = crear("path", "vibi-antifaz");
  antifaz.setAttribute("d", ANTIFAZ);
  antifaz.setAttribute("fill", color("--vibi-antifaz", "#0c0714"));
  recortado.appendChild(antifaz);

  const llama = crear("g", "vibi-llama");
  const lenguas = LENGUAS.map((sitio) => {
    const fuera = crear("g");
    fuera.setAttribute(
      "transform",
      `translate(${sitio.x} ${sitio.y}) rotate(${sitio.giro}) scale(${sitio.escala})`,
    );
    const dentro = crear("g", "vibi-lengua");
    const forma = crear("path");
    forma.setAttribute("d", LENGUA);
    if (sitio.perfilada) {
      forma.setAttribute("fill", color("--vibi-carne", "#ffffff"));
      forma.setAttribute("stroke", color("--vibi-rojo", "#f4121b"));
      forma.setAttribute("stroke-width", "4.5");
      forma.setAttribute("stroke-linejoin", "round");
    } else {
      forma.setAttribute("fill", color("--vibi-rojo", "#f4121b"));
    }
    dentro.appendChild(forma);
    fuera.appendChild(dentro);
    llama.appendChild(fuera);
    return dentro;
  });

  const ala = crear("g", "vibi-ala");
  const alaForma = crear("path");
  alaForma.setAttribute("d", ALA);
  alaForma.setAttribute("fill", color("--vibi-rojo", "#f4121b"));
  ala.appendChild(alaForma);

  const gesto = crear("g", "vibi-gesto");
  const ojos = OJOS.map(() => {
    const nodo = crear("path", "vibi-ojo");
    nodo.setAttribute("fill", color("--vibi-carne", "#ffffff"));
    // El contorno da la línea media; el trazo del mismo color le devuelve el
    // bulto que en la lámina ponía el `stroke`. Con grosor cero no pinta nada.
    nodo.setAttribute("stroke", color("--vibi-carne", "#ffffff"));
    nodo.setAttribute("stroke-linejoin", "round");
    gesto.appendChild(nodo);
    return nodo;
  });
  const pupilas = OJOS.map(() => {
    const nodo = crear("circle", "vibi-pupila");
    nodo.setAttribute("r", "8");
    nodo.setAttribute("fill", color("--vibi-antifaz", "#0c0714"));
    gesto.appendChild(nodo);
    return nodo;
  });
  const boca = crear("path", "vibi-boca");
  boca.setAttribute("d", BOCA);
  boca.setAttribute("fill", "none");
  boca.setAttribute("stroke", color("--vibi-carne", "#ffffff"));
  boca.setAttribute("stroke-width", String(GROSOR_BOCA));
  boca.setAttribute("stroke-linecap", "round");
  gesto.appendChild(boca);

  // --- los complementos, montados una vez y encendidos por opacidad
  const interrogacion = crear("g", "vibi-interrogacion");
  {
    const cuerpoSigno = crear("path");
    cuerpoSigno.setAttribute("d", INTERROGACION.cuerpo);
    const punto = crear("circle");
    punto.setAttribute("cx", String(INTERROGACION.punto.x));
    punto.setAttribute("cy", String(INTERROGACION.punto.y));
    punto.setAttribute("r", String(INTERROGACION.punto.r));
    for (const nodo of [cuerpoSigno, punto]) {
      nodo.setAttribute("fill", color("--vibi-rojo", "#f4121b"));
      // Cae justo encima del fuego: en rojo sobre rojo desaparecía.
      nodo.setAttribute("stroke", color("--vibi-antifaz", "#0c0714"));
      nodo.setAttribute("stroke-width", "9");
      nodo.setAttribute("stroke-linejoin", "round");
      nodo.setAttribute("paint-order", "stroke");
      interrogacion.appendChild(nodo);
    }
  }

  const onda = crear("g", "vibi-onda");
  const barras = ONDA.alturas.map((alto, i) => {
    const nodo = crear("rect", "vibi-barra");
    nodo.setAttribute("x", String(ONDA.x + i * ONDA.paso));
    nodo.setAttribute("y", String(ONDA.y - alto / 2));
    nodo.setAttribute("width", String(ONDA.ancho));
    nodo.setAttribute("height", String(alto));
    nodo.setAttribute("rx", String(ONDA.ancho / 2));
    nodo.setAttribute("fill", color("--vibi-rojo", "#f4121b"));
    onda.appendChild(nodo);
    return nodo;
  });

  const lupa = crear("g", "vibi-lupa");
  {
    const cristal = crear("circle");
    cristal.setAttribute("cx", String(LUPA.cx));
    cristal.setAttribute("cy", String(LUPA.cy));
    cristal.setAttribute("r", String(LUPA.r));
    cristal.setAttribute("fill", "none");
    cristal.setAttribute("stroke", color("--vibi-rojo", "#f4121b"));
    cristal.setAttribute("stroke-width", String(LUPA.grosor));
    const mango = crear("path");
    mango.setAttribute("d", LUPA.mango);
    mango.setAttribute("fill", "none");
    mango.setAttribute("stroke", color("--vibi-rojo", "#f4121b"));
    mango.setAttribute("stroke-width", String(LUPA.grosorMango));
    mango.setAttribute("stroke-linecap", "round");
    lupa.append(cristal, mango);
  }

  const martillo = crear("g", "vibi-martillo");
  {
    const mango = crear("path");
    mango.setAttribute("d", MARTILLO.mango);
    mango.setAttribute("fill", "none");
    mango.setAttribute("stroke", color("--vibi-rojo", "#f4121b"));
    mango.setAttribute("stroke-width", String(MARTILLO.grosorMango));
    mango.setAttribute("stroke-linecap", "round");
    const cabeza = crear("rect");
    cabeza.setAttribute("x", String(MARTILLO.cabeza.x));
    cabeza.setAttribute("y", String(MARTILLO.cabeza.y));
    cabeza.setAttribute("width", String(MARTILLO.cabeza.ancho));
    cabeza.setAttribute("height", String(MARTILLO.cabeza.alto));
    cabeza.setAttribute("rx", String(MARTILLO.cabeza.rx));
    cabeza.setAttribute("fill", color("--vibi-rojo", "#f4121b"));
    martillo.append(mango, cabeza);
  }

  cuerpo.append(
    copa, carne, recortado, llama, ala, gesto, interrogacion, onda, lupa, martillo,
  );
  figura.appendChild(cuerpo);
  svg.appendChild(figura);
  contenedor.appendChild(svg);

  // ------------------------------------------------------------ la maquinaria
  const formas = crearOjos();
  const sacadas = crearSacadas();
  const parpadeo = crearParpadeo();
  const puntero = crearSeguimientoPuntero();

  const cuerpoY: Muelle = crearMuelle(0);
  const cuerpoGiro: Muelle = crearMuelle(0);
  const sombreroY: Muelle = crearMuelle(0);
  const sombreroGiro: Muelle = crearMuelle(0);
  /** El empujón del cambio de estado. Vuelve solo a cero, pasándose de frenada. */
  const sacudida: Muelle = crearMuelle(0);

  let miradaX = 0;
  let miradaY = 0;
  /** El grosor de cada ojo, que viaja con el morfeo en vez de saltar. */
  let perfilIzq = 0;
  let perfilDer = 0;
  let objetivoX = 0;
  let objetivoY = 0;
  let pupila = 0;
  let visibleBoca = 0;
  const encendido: Record<Complemento, number> = {
    ninguno: 0,
    interrogacion: 0,
    onda: 0,
    lupa: 0,
    martillo: 0,
  };

  let vivo = true;
  let pedido = 0;
  let ultimaMarca = 0;
  let reloj = 0;
  let estado: FaceState = "idle";
  let senales: Senales = SENALES_QUIETAS;

  /** El eje sobre el que se ladea la cabeza: la barbilla, no el centro. */
  const EJE = { x: 150, y: 258 };
  /** El del sombrero, donde el ala se apoya en la cabeza. */
  const EJE_SOMBRERO = { x: 128, y: 132 };

  const pintar = (dt: number) => {
    const plan = gestoDe(estado);
    const porte = plan.porte;
    const ajustes = ajustesDe(senales, Date.now());
    const voz = nivelDeVoz();

    // --- adónde mira. El cursor manda sobre el gesto: si le prestas atención,
    // te mira, y eso es un seguimiento y no una sacada.
    const raton = perfil === "companion" ? puntero.avanzar(dt) : null;
    if (raton) {
      objetivoX = acotar(raton.x, -1, 1) * 8;
      objetivoY = acotar(raton.y, -1, 1) * 5;
    } else {
      const salto = sacadas.avanzar(plan.sacada, dt);
      if (salto) {
        objetivoX = acotar(salto.yaw / 26, -1, 1) * 8;
        objetivoY = acotar(salto.pitch / 13, -1, 1) * 5;
      }
    }
    // Cuarenta y cinco milisegundos es lo que tarda un ojo humano en saltar.
    miradaX = suavizar(miradaX, objetivoX, dt, 0.045);
    miradaY = suavizar(miradaY, objetivoY, dt, 0.045);

    // --- el cuerpo
    const vaiven = Math.sin(reloj * porte.vaiven[0] * Math.PI * 2) * porte.vaiven[1];
    const cicloBrinco = 1.15;
    const salto =
      porte.brinco > 0
        ? -porte.brinco * 24 * pulso(Math.min(1, ((reloj % cicloBrinco) / cicloBrinco) / 0.62))
        : 0;
    const tembleque = porte.tension * 1.7 * meneo(reloj * 13, 3.1);

    const destinoY = vaiven + salto + tembleque;
    // El cursor y el trabajo en otro equipo empujan el ladeo; el resto lo pone
    // el gesto y se queda.
    const destinoGiro =
      porte.ladeo +
      (raton ? acotar(raton.x, -1, 1) * 5 : miradaX * 0.22) +
      ajustes.inclinacionRemota * 0.4 +
      porte.tension * 1.1 * meneo(reloj * 11, 7.7);

    avanzarMuelle(cuerpoY, destinoY, dt, 210, 26);
    avanzarMuelle(cuerpoGiro, destinoGiro, dt, 190, 24);

    // El sombrero persigue a la cabeza con un muelle más blando, y por eso
    // llega tarde y se pasa de frenada. Ese retraso es el movimiento secundario.
    const amortiguacion = 1.55 * Math.sqrt(porte.garbo);
    avanzarMuelle(sombreroY, cuerpoY.valor, dt, porte.garbo, amortiguacion);
    avanzarMuelle(sombreroGiro, cuerpoGiro.valor * 1.4, dt, porte.garbo, amortiguacion);

    // El empujón del cambio de estado, volviendo a cero.
    avanzarMuelle(sacudida, 0, dt, 165, 13);
    const golpe = acotar(sacudida.valor, -1.4, 1.4);

    cuerpo.setAttribute(
      "transform",
      plantar(0, cuerpoY.valor, cuerpoGiro.valor - golpe * 5, 1 - golpe * 0.09, 1 + golpe * 0.11, EJE.x, EJE.y),
    );
    const matrizSombrero = plantar(
      0,
      sombreroY.valor - cuerpoY.valor,
      sombreroGiro.valor - cuerpoGiro.valor - golpe * 3,
      1,
      1,
      EJE_SOMBRERO.x,
      EJE_SOMBRERO.y,
    );
    copa.setAttribute("transform", matrizSombrero);
    ala.setAttribute("transform", matrizSombrero);

    // --- el fuego. Arde con lo que está pasando, no con un reloj suyo.
    const ardor = acotar(
      porte.ardor + ajustes.pulsoHabla * 0.55 + voz * 0.45 + ajustes.impulsoCorte * 0.4,
      0,
      1.4,
    );
    lenguas.forEach((nodo, i) => {
      const alto = 1 + meneo(reloj * 1.5 * LENGUAS[i].prisa, i * 2.1) * (0.12 + ardor * 0.3);
      nodo.setAttribute("transform", `scale(${(1 - (alto - 1) * 0.55).toFixed(4)} ${alto.toFixed(4)})`);
    });
    // El fuego solo se apaga en los estados que están de verdad apagados —sin
    // canal, vigilando—, y no en cuanto baja el ardor. Escalado sobre el rango
    // entero se quedaba al 34% en reposo, y una llama translúcida sobre la
    // sombra proyectada se ve rosa, no tenue.
    llama.setAttribute("opacity", (0.3 + acotar(ardor / 0.15, 0, 1) * 0.7).toFixed(3));

    // --- los ojos
    const [dIzq, dDer] = formas.trazar(plan.ojo, plan.ojoDer ?? plan.ojo, dt);
    const cerrado = CERRADOS.has(plan.ojo);
    const apertura = cerrado ? 1 : parpadeo.avanzar(dt);
    // El mismo suavizado que el morfeo, para que el grosor llegue con la forma.
    perfilIzq = suavizar(perfilIzq, PERFILADO[plan.ojo], dt, 0.16);
    perfilDer = suavizar(perfilDer, PERFILADO[plan.ojoDer ?? plan.ojo], dt, 0.16);
    ojos.forEach((nodo, i) => {
      const sitio = OJOS[i];
      nodo.setAttribute("d", i === 0 ? dIzq : dDer);
      nodo.setAttribute("stroke-width", (i === 0 ? perfilIzq : perfilDer).toFixed(2));
      nodo.setAttribute(
        "transform",
        `translate(${(sitio.x + miradaX).toFixed(2)} ${(sitio.y + miradaY).toFixed(2)}) scale(1 ${apertura.toFixed(3)})`,
      );
    });

    pupila = suavizar(pupila, plan.ojo === "redondo" ? 1 : 0, dt, 0.1);
    pupilas.forEach((nodo, i) => {
      const sitio = OJOS[i];
      nodo.setAttribute("cx", (sitio.x + miradaX * 1.7).toFixed(2));
      nodo.setAttribute("cy", (sitio.y + miradaY * 1.7).toFixed(2));
      nodo.setAttribute("opacity", (pupila * apertura).toFixed(3));
    });

    visibleBoca = suavizar(visibleBoca, plan.boca ? 1 : 0, dt, 0.12);
    boca.setAttribute("opacity", visibleBoca.toFixed(3));
    const ensancha = 1 + Math.sin(reloj * porte.vaiven[0] * Math.PI * 2) * 0.05;
    boca.setAttribute("transform", plantar(0, 0, 0, ensancha, 1, 158, 224));

    // --- los complementos
    for (const clave of ["interrogacion", "onda", "lupa", "martillo"] as const) {
      encendido[clave] = suavizar(encendido[clave], plan.complemento === clave ? 1 : 0, dt, 0.14);
    }

    // La interrogación no se queda puesta: asoma, sube y se apaga. Una cara que
    // se queda con el gesto de la duda parece rota, no dubitativa.
    const ciclo = (reloj % 2.6) / 2.6;
    interrogacion.setAttribute("opacity", (encendido.interrogacion * asomo(ciclo)).toFixed(3));
    interrogacion.setAttribute(
      "transform",
      `translate(${INTERROGACION.x} ${(INTERROGACION.y + 6 - ciclo * 18).toFixed(2)}) ` +
        `scale(${INTERROGACION.escala})`,
    );

    onda.setAttribute("opacity", encendido.onda.toFixed(3));
    if (encendido.onda > 0.01) {
      // La onda enseña lo que de verdad está pasando: el micrófono cuando te
      // escucha, y el caudal de tokens cuando contesta. Es el mismo dato que
      // `voice.ts` ya medía para saber cuándo te callas y luego tiraba.
      const fuerza = Math.max(voz, ajustes.pulsoHabla);
      barras.forEach((nodo, i) => {
        const escala = acotar(0.3 + fuerza * 0.95 + meneo(reloj * 5.5, i * 1.7) * 0.14, 0.12, 1.6);
        nodo.setAttribute(
          "transform",
          plantar(0, 0, 0, 1, escala, ONDA.x + i * ONDA.paso + ONDA.ancho / 2, ONDA.y),
        );
      });
    }

    lupa.setAttribute("opacity", encendido.lupa.toFixed(3));
    if (encendido.lupa > 0.01) {
      const t = reloj * 2.4;
      const escala = 1 + Math.sin(t * 1.3) * 0.08;
      lupa.setAttribute(
        "transform",
        plantar(Math.sin(t) * -13, Math.cos(t * 0.8) * 9, 0, escala, escala, LUPA.cx, LUPA.cy),
      );
    }

    martillo.setAttribute("opacity", encendido.martillo.toFixed(3));
    if (encendido.martillo > 0.01) {
      const alzada = martillazo((reloj % MARTILLO.compas) / MARTILLO.compas);
      const giro = MARTILLO.golpe + (MARTILLO.alzado - MARTILLO.golpe) * alzada;
      martillo.setAttribute(
        "transform",
        plantar(0, 0, giro, 1, 1, MARTILLO.eje.x, MARTILLO.eje.y),
      );
    }
  };

  const dibujar = (delta: number) => {
    if (!vivo) return;
    const paso = Number.isFinite(delta) ? Math.min(Math.max(delta, 0), 0.05) : 1 / 60;
    reloj += paso;
    pintar(paso);
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
    if (delta < cadenciaDe(estado, puntero.activo)) return;
    ultimaMarca = segundos;
    dibujar(delta);
  };

  // El primer fotograma va ya, sin esperar al bucle: si no, se ve el hueco. Y
  // los muelles arrancan plantados, para que la cara no entre dando un salto.
  fijarMuelle(cuerpoY, 0);
  fijarMuelle(cuerpoGiro, gestoDe(estado).porte.ladeo);
  fijarMuelle(sombreroY, 0);
  fijarMuelle(sombreroGiro, gestoDe(estado).porte.ladeo);
  dibujar(1 / 60);
  pedido = requestAnimationFrame(bucle);

  return {
    setState(nuevo) {
      if (!vivo || nuevo === estado) return;
      estado = nuevo;
      // El empujón: la cabeza se aplasta y se ladea, y el muelle la devuelve.
      // Aquí es donde vive la transición entre caras, y es una sola para las
      // treinta y dos porque la dicta la física y no una tabla de pares.
      sacudida.velocidad += 9;
      // Y la mirada salta en el fotograma siguiente en vez de esperar a que
      // venza la espera del gesto anterior.
      sacadas.reiniciar();
    },
    setSenales(nuevas) {
      if (vivo) senales = nuevas;
    },
    setPointer(x, y) {
      if (vivo && perfil === "companion") puntero.apuntar(x, y);
    },
    clearPointer() {
      puntero.soltar();
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
