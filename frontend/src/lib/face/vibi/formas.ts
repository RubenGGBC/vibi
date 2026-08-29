/**
 * Las formas de los ojos, y cómo se pasa de una a otra.
 *
 * La técnica es la de `ojos.ts` y se conserva entera porque es la que hace
 * falta: **todos los contornos se muestrean con los MISMOS puntos y en el mismo
 * sentido**, que es lo único que permite morfar punto a punto. Sin esa regla,
 * pasar de una píldora a un chevrón daría un revoltijo — y es exactamente lo
 * que una librería de morfeo de trazados tendría que adivinar por su cuenta.
 *
 * Lo que cambia respecto a la cara anterior es el catálogo, no el mecanismo: el
 * personaje nuevo no tiene ojos perforados en una masa, tiene rasgos blancos
 * pintados sobre el antifaz, y dos de ellos ni siquiera son ojos —el guion y el
 * chevrón del `->`— pero se dibujan por el mismo carril porque van en el mismo
 * sitio y tienen que poder salir de una píldora y volver a ella.
 *
 * Cada forma va ya **inclinada en su propia definición**. La alternativa era
 * girarlas desde la escena, y entonces el ángulo del ojo y la escala del
 * parpadeo se pelean por el mismo atributo `transform`.
 */

/** Puntos por contorno. Treinta y dos bastan para que una curva de dos tramos se lea redonda. */
const M = 32;

export type FormaOjo =
  /** El reposo: una píldora de pie, ligeramente caída. */
  | "pildora"
  /** Redondo del todo. Dudar, y mirarte fijo. */
  | "redondo"
  /** Rendija: dormir, vigilar, y quedarse sin servidor. */
  | "rendija"
  /** Arco hacia arriba. Alegrarse. */
  | "alegre"
  /** Arco hacia abajo: los párpados echados de quien habla tranquila. */
  | "sosiego"
  /** La cuña del recelo, ojo izquierdo. */
  | "furia"
  /** La misma cuña reflejada, para el derecho. Recelar no es simétrico. */
  | "furiaDer"
  /** El guion del `->`. */
  | "guion"
  /** El chevrón del `->`. */
  | "punta";

interface Punto {
  x: number;
  y: number;
}

const TAU = Math.PI * 2;

const muestrear = (fn: (u: number) => Punto): Punto[] =>
  Array.from({ length: M }, (_, i) => fn(i / M));

const pot = (v: number, e: number) => Math.sign(v) * Math.pow(Math.abs(v), e);

/**
 * Superelipse. `n` a 2 es una elipse; subiéndolo se acerca a una píldora.
 *
 * Empieza por el punto de la derecha y avanza en el sentido de las agujas del
 * reloj (en pantalla, donde la `y` crece hacia abajo). Todas las demás formas
 * se construyen para arrancar y girar igual.
 */
const supe = (ancho: number, alto: number, n: number): Punto[] =>
  muestrear((u) => {
    const a = u * TAU;
    return {
      x: (ancho / 2) * pot(Math.cos(a), 2 / n),
      y: (alto / 2) * pot(Math.sin(a), 2 / n),
    };
  });

/**
 * Una banda curva centrada en el origen: la sonrisa de los ojos, y del revés
 * los párpados echados. `signo` -1 levanta la cresta y +1 la hunde.
 */
const arcoBanda = (ancho: number, alto: number, grosor: number, signo: number): Punto[] => {
  const centro = ((alto + grosor) / 2) * signo;
  return muestrear((u) => {
    const ida = u < 0.5;
    const v = ida ? u * 2 : (1 - u) * 2;
    return {
      x: (0.5 - v) * ancho,
      y: Math.sin(v * Math.PI) * alto * signo + (ida ? grosor * signo : 0) - centro,
    };
  });
};

/**
 * Lo cerca que se plantan los puntos de apoyo a cada esquina.
 *
 * `trazarContorno` usa los puntos medios como anclas, así que **cada esquina se
 * redondea con la mitad de la distancia a sus vecinos**. Repartiendo los treinta
 * y dos puntos a partes iguales, un cuadrilátero acaba con ocho unidades entre
 * punto y punto y la cuña del recelo sale convertida en una alubia — que es
 * exactamente lo que pasó la primera vez. Con los apoyos a punto y medio, la
 * esquina se redondea con menos de una unidad y se lee afilada.
 */
const APOYO = 1.4;

/**
 * Un contorno recto, con las esquinas conservadas.
 *
 * Cada vértice se lleva tres puntos —el de llegada, la esquina y el de salida—
 * y los que sobran se reparten por los lados en proporción a lo que miden: si
 * se repartieran por vértice, un lado largo tendría los mismos que uno corto y
 * el morfeo tiraría de la forma por donde no debe.
 */
const poligono = (vertices: ReadonlyArray<readonly [number, number]>): Punto[] => {
  const V = vertices.length;
  const sueltos = M - 3 * V;
  if (sueltos < 0) throw new Error(`${V} vértices no caben en ${M} puntos`);

  const lados = vertices.map((a, i) => {
    const b = vertices[(i + 1) % V];
    return { a, b, largo: Math.hypot(b[0] - a[0], b[1] - a[1]) };
  });
  const total = lados.reduce((s, l) => s + l.largo, 0);
  const reparto = lados.map((l) => Math.floor((sueltos * l.largo) / total));
  // El redondeo hacia abajo deja siempre algún punto sin colocar; van a los
  // lados más largos, que es donde menos se nota tener uno más.
  const porLargo = lados.map((_, i) => i).sort((x, y) => lados[y].largo - lados[x].largo);
  const sobra = sueltos - reparto.reduce((x, y) => x + y, 0);
  for (let k = 0; k < sobra; k += 1) reparto[porLargo[k % V]] += 1;

  const pts: Punto[] = [];
  for (let i = 0; i < V; i += 1) {
    const { a, b, largo } = lados[i];
    const ux = (b[0] - a[0]) / largo;
    const uy = (b[1] - a[1]) / largo;
    const d = Math.min(APOYO, largo / 3);
    pts.push({ x: a[0], y: a[1] });
    pts.push({ x: a[0] + ux * d, y: a[1] + uy * d });
    for (let k = 1; k <= reparto[i]; k += 1) {
      const t = d + ((largo - 2 * d) * k) / (reparto[i] + 1);
      pts.push({ x: a[0] + ux * t, y: a[1] + uy * t });
    }
    pts.push({ x: b[0] - ux * d, y: b[1] - uy * d });
  }
  return pts;
};

/** Inclina un contorno ya muestreado. Lo usan las formas que van caídas. */
const inclinar = (pts: Punto[], grados: number): Punto[] => {
  const a = (grados * Math.PI) / 180;
  const c = Math.cos(a);
  const s = Math.sin(a);
  return pts.map((p) => ({ x: p.x * c - p.y * s, y: p.x * s + p.y * c }));
};

/** Refleja un contorno. Recelar no es simétrico: el ojo derecho es este espejo. */
const espejo = (pts: Punto[]): Punto[] => pts.map((p) => ({ x: -p.x, y: p.y }));

/** El área con signo. Positiva es el sentido de las agujas del reloj en pantalla, donde la `y` crece hacia abajo. */
const area = (pts: ReadonlyArray<Punto>): number =>
  pts.reduce((suma, a, i) => {
    const b = pts[(i + 1) % pts.length];
    return suma + (a.x * b.y - b.x * a.y);
  }, 0);

/**
 * Deja el contorno como los espera el morfeo: girando en el sentido de las
 * agujas del reloj y empezando por el punto más a la derecha.
 *
 * Se hace **por construcción y no a ojo** porque es la condición que se rompe
 * en silencio. Un contorno reflejado gira al revés, y morfar contra él lo
 * desenrolla: se ve como un latigazo de dos décimas y no hay forma de adivinar
 * de dónde sale mirando el catálogo, porque las dos formas son correctas.
 */
const normalizar = (pts: Punto[]): Punto[] => {
  const derecho = area(pts) < 0 ? [...pts].reverse() : pts;
  let inicio = 0;
  for (let i = 1; i < derecho.length; i += 1) {
    if (derecho[i].x > derecho[inicio].x) inicio = i;
  }
  return [...derecho.slice(inicio), ...derecho.slice(0, inicio)];
};

/**
 * El chevrón, calculado y no dibujado a ojo.
 *
 * Es el perfil de un trazo de grosor `g` sobre la polilínea extremo-punta-
 * extremo. La esquina de dentro se saca del bisector —a `g/2 / sin(mitad del
 * ángulo)` de la punta—, que es el único punto que no se puede poner a ojo sin
 * que el vértice quede mordido.
 */
const chevron = (largoX: number, largoY: number, g: number): Punto[] => {
  const brazo = Math.hypot(largoX, largoY);
  const mitad = Math.atan2(largoY, largoX);
  // Normal de cada brazo hacia fuera, ya escalada a medio grosor.
  const dx = ((g / 2) * largoY) / brazo;
  const dy = ((g / 2) * largoX) / brazo;
  const px = largoX / 2;
  const ex = -largoX / 2;
  // La esquina de dentro sale del bisector, no del borde: puesta a ojo, el
  // vértice queda mordido o le sobra un pico.
  const dentro = px - g / 2 / Math.sin(mitad);
  return poligono([
    [px + dx, dy],
    [ex + dx, largoY + dy],
    [ex - dx, largoY - dy],
    [dentro, 0],
    [ex - dx, -largoY + dy],
    [ex + dx, -largoY - dy],
    [px + dx, -dy],
  ]);
};

/** La cuña del recelo, medida desde el anclaje del ojo y no desde el lienzo. */
const CUNA = poligono([
  [17, 6],
  [9, 20],
  [-26, -1],
  [-23, -19],
]);

const FORMAS: Record<FormaOjo, Punto[]> = Object.fromEntries(
  Object.entries({
    // Un `n` de seis salía cuadrada: la píldora del diseño tiene los lados
    // rectos pero las puntas redondas del todo, y eso cae más cerca de cuatro.
    pildora: inclinar(supe(19, 31, 4.2), -10),
    redondo: supe(32, 32, 2),
    rendija: inclinar(supe(28, 9, 6), -6),
    alegre: arcoBanda(44, 24, 9, -1),
    // La banda de los párpados iba a veintisiete de alto y se leía como un
    // manchón blanco en vez de como un ojo cerrado. Veintiuno la deja fina.
    sosiego: arcoBanda(42, 13, 8, 1),
    furia: CUNA,
    furiaDer: espejo(CUNA),
    // El guion y el chevrón se miden con los remates puestos: en la lámina son
    // trazos de once con la punta redonda, así que ocupan once más de lo que
    // mide su eje. Sin eso, el `->` sale corto y flojo.
    guion: supe(53, 11, 6),
    punta: chevron(40, 21, 11),
  }).map(([nombre, pts]) => [nombre, normalizar(pts)]),
) as Record<FormaOjo, Punto[]>;

/**
 * Lo que hay que engordar cada forma al pintarla, en unidades de vista.
 *
 * En la lámina los rasgos son trazos —`fill` más `stroke`—, y aquí tienen que
 * ser contornos cerrados para poder morfar punto a punto. El contorno da la
 * línea media, no el bulto: la cuña del recelo salía un tercio más flaca que la
 * dibujada. En vez de mover los vértices —que en un cuadrilátero cóncavo no es
 * un simple escalado— se le devuelve el grosor con un `stroke` del mismo color,
 * que es literalmente lo que hacía la lámina.
 *
 * Interpola como una más: al morfar de una píldora a una cuña, el grosor viaja
 * con la forma.
 */
export const PERFILADO: Record<FormaOjo, number> = {
  pildora: 0,
  redondo: 0,
  rendija: 0,
  alegre: 0,
  sosiego: 0,
  furia: 6,
  furiaDer: 6,
  guion: 0,
  punta: 0,
};

/** El trazado de un contorno, con los puntos medios como anclas: sale suave sin calcular tangentes. */
export function trazarContorno(pts: Punto[]): string {
  // El cero negativo se imprime como `-0.00`, así que la misma geometría podía
  // salir con dos textos distintos y hacer que el atributo cambiara sin que
  // nada se hubiera movido.
  const n = (v: number) => (Math.abs(v) < 0.005 ? "0.00" : v.toFixed(2));
  const medio = (a: Punto, b: Punto) => `${n((a.x + b.x) / 2)} ${n((a.y + b.y) / 2)}`;
  let d = `M${medio(pts[M - 1], pts[0])}`;
  for (let i = 0; i < M; i += 1) {
    const a = pts[i];
    const b = pts[(i + 1) % M];
    d += `Q${n(a.x)} ${n(a.y)} ${medio(a, b)}`;
  }
  return `${d}Z`;
}

export interface Ojos {
  /** Avanza el morfeo un paso y devuelve los dos trazados, izquierdo y derecho. */
  trazar(izquierdo: FormaOjo, derecho: FormaOjo, dt: number): [string, string];
}

/** Lo que tarda un ojo en cambiar de forma. Corto: llega antes que el cuerpo, a propósito. */
const MORFEO = 0.16;

export function crearOjos(): Ojos {
  const vivo: [Punto[], Punto[]] = [
    FORMAS.pildora.map((p) => ({ ...p })),
    FORMAS.pildora.map((p) => ({ ...p })),
  ];

  return {
    trazar(izquierdo, derecho, dt) {
      const paso = Number.isFinite(dt) ? Math.min(Math.max(dt, 0), 0.1) : 0;
      // Suavizado exponencial: independiente de la cadencia, así que bajar a 24
      // fotogramas en reposo no ralentiza el cambio de gesto.
      const k = 1 - Math.exp(-paso / MORFEO);
      const destino = [FORMAS[izquierdo] ?? FORMAS.pildora, FORMAS[derecho] ?? FORMAS.pildora];
      for (let o = 0; o < 2; o += 1) {
        for (let i = 0; i < M; i += 1) {
          vivo[o][i].x += (destino[o][i].x - vivo[o][i].x) * k;
          vivo[o][i].y += (destino[o][i].y - vivo[o][i].y) * k;
        }
      }
      return [trazarContorno(vivo[0]), trazarContorno(vivo[1])];
    },
  };
}

/** Para las pruebas: cuántos puntos tiene cada contorno, y el catálogo crudo. */
export const PUNTOS_POR_FORMA = M;
export const CATALOGO = FORMAS;
