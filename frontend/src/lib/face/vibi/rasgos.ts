/**
 * La geometría fija de Vibi: la chistera, la cabeza, el antifaz y el fuego.
 *
 * Son las piezas que **no** cambian con el gesto. Lo que cambia son los ojos,
 * la boca y el complemento, y eso vive en `formas.ts`; aquí solo está el
 * personaje quieto.
 *
 * Los números salen de la lámina de diseño y se copian tal cual: cada uno se
 * ajustó mirando el dibujo montado, así que redondearlos «para que queden
 * bonitos» deshace media tarde de encaje. En particular el borde de arriba de
 * la copa es una **recta escorada** y no una cúpula — en cuanto se curva, deja
 * de ser una chistera y se convierte en un gorro de cocinero.
 *
 * El sistema de coordenadas tiene aire de sobra por arriba y por los lados
 * respecto al personaje (que vive en 0..300): el rebote de alegrarse sube
 * veintidós unidades y la sombra proyectada se sale otras tantas, y sin ese
 * margen el filtro las recorta y se ve el corte.
 */

export const VISTA = { x: -26, y: -58, ancho: 358, alto: 400 } as const;

/** La cabeza: ancha, con la barbilla cayendo hacia abajo y a la izquierda. */
export const CABEZA =
  "M 52 178 C 50 130 92 90 152 90 C 214 90 252 128 254 180 " +
  "C 256 224 232 256 194 268 C 162 278 122 282 96 268 " +
  "C 68 253 54 224 52 178 Z";

/**
 * El antifaz negro.
 *
 * Se recorta contra la silueta de la cabeza, así que puede desbordar por todos
 * lados sin cuidado: lo único que importa es por dónde pasa el borde de abajo,
 * que es el que deja el blanco como una media luna que sube por la izquierda.
 */
export const ANTIFAZ =
  "M 12 8 H 296 V 192 C 254 198 238 236 202 242 " +
  "C 176 247 158 232 130 242 C 104 252 66 232 44 188 L 12 188 Z";

/** La copa. La base se mete debajo del ala, así que no hace falta cerrarla con gracia. */
export const COPA =
  "M 34 46 C 33 28 44 18 64 14 L 154 -8 C 174 -13 187 -4 188 13 " +
  "L 196 122 L 50 136 Z";

/**
 * Los dos pliegues de la copa.
 *
 * Arrancan **por debajo del borde de arriba**, que baja de derecha a izquierda:
 * en x=104 la copa empieza en y≈4 y en x=128 en y≈-2. Empezándolos en el cero
 * asomaban por encima del sombrero y se leían como dos antenas.
 *
 * El segundo arranca más abajo que el primero para que juntos cuenten un doblez
 * y no dos dedos.
 */
export const PLIEGUES: ReadonlyArray<{ d: string; grosor: number }> = [
  { d: "M 104 14 C 94 46 96 92 104 128", grosor: 7 },
  { d: "M 128 26 C 134 56 137 94 141 122", grosor: 4.5 },
];

/** El ala: la diagonal que ordena todo el dibujo. Arranca abajo a la izquierda y sale en punta arriba a la derecha. */
export const ALA =
  "M 22 124 C 2 142 8 172 36 178 C 88 192 158 176 210 144 " +
  "C 240 126 258 102 258 82 C 258 68 242 66 232 78 " +
  "C 198 114 114 136 56 118 C 38 112 28 114 22 124 Z";

/** Una lengua de fuego, con la punta hacia arriba y la base en el origen. */
export const LENGUA = "M 0 0 C -11 -12 -8 -28 2 -42 C 1 -26 12 -22 10 -8 C 9 0 4 5 0 0 Z";

export interface Colocacion {
  x: number;
  y: number;
  giro: number;
  escala: number;
  /** Blanca perfilada de rojo, o roja maciza por detrás. */
  perfilada: boolean;
  /** Multiplica la velocidad del titileo: las pequeñas van más nerviosas. */
  prisa: number;
}

/**
 * Las seis lenguas del costado derecho.
 *
 * Las tres rojas van detrás y las tres blancas delante; el desfase entre unas y
 * otras es lo que hace que el fuego no se lea como una sola forma latiendo.
 */
export const LENGUAS: readonly Colocacion[] = [
  { x: 220, y: 242, giro: -8, escala: 1.7, perfilada: false, prisa: 0.78 },
  { x: 248, y: 214, giro: 12, escala: 1.35, perfilada: false, prisa: 1 },
  { x: 264, y: 180, giro: 32, escala: 0.95, perfilada: false, prisa: 1.32 },
  { x: 234, y: 234, giro: 4, escala: 2.05, perfilada: true, prisa: 0.66 },
  { x: 256, y: 196, giro: 22, escala: 1.6, perfilada: true, prisa: 0.87 },
  { x: 266, y: 158, giro: 40, escala: 1.05, perfilada: true, prisa: 1.15 },
];

/** Dónde se posa cada ojo, y con cuánta caída. El derecho va un poco más alto: la cabeza está ladeada. */
export const OJOS = [
  { x: 128, y: 205, giro: -12 },
  { x: 182, y: 199, giro: -8 },
] as const;

/**
 * La boca de trabajar. Va sola porque es el único gesto que la enseña.
 *
 * Cabe justa: por arriba la limita el ojo izquierdo (que acaba en x=138) y por
 * abajo el borde del antifaz (y≈242 en el centro). Dibujada más ancha o más
 * baja se sale al blanco de la mandíbula y **desaparece**, que es un fallo que
 * no da ningún error: simplemente el gesto de trabajar deja de tener boca.
 */
export const BOCA = "M 140 218 Q 158 230 177 216";
export const GROSOR_BOCA = 8.5;

/**
 * La interrogación, dibujada y no escrita.
 *
 * Con `<text>` dependería de que cargue una fuente, y al exportar cae en la de
 * repuesto y cambia de peso. Va perfilada en negro porque cae justo encima del
 * fuego: en rojo sobre rojo desaparecía, y es el único rasgo que cuenta el gesto.
 */
export const INTERROGACION = {
  x: 276,
  y: 26,
  escala: 1.2,
  cuerpo:
    "M -1 -44 C 16 -44 29 -34 29 -19 C 29 -6 19 1 13 7 C 8 12 6 17 6 24 L -9 24 " +
    "C -9 13 -7 6 1 -2 C 8 -9 14 -13 14 -20 C 14 -28 8 -32 -1 -32 C -10 -32 -16 -26 -16 -17 " +
    "L -31 -17 C -31 -34 -18 -44 -1 -44 Z",
  punto: { x: -2, y: 41, r: 10 },
} as const;

/**
 * Las cinco barras de la onda. La altura es la de reposo; el nivel de voz las estira.
 *
 * El hueco entre barras tiene que ser mayor que el desplazamiento de la sombra
 * proyectada (cuatro unidades, en `cara.css`): con el paso a quince y el ancho
 * a once quedaban cuatro de hueco, así que **cada barra caía dentro de la
 * sombra de su vecina** y las cinco se veían granates en vez de rojas.
 */
export const ONDA = {
  x: 240,
  y: 284,
  paso: 20,
  ancho: 11,
  alturas: [26, 44, 62, 40, 28],
} as const;

/** La lupa. Va abajo a la derecha, por debajo del fuego, que es donde queda sitio limpio. */
export const LUPA = {
  cx: 266,
  cy: 262,
  r: 26,
  grosor: 10,
  mango: "M 285 281 L 306 303",
  grosorMango: 13,
} as const;

/**
 * El martillo de la forja. Ocupa el mismo sitio que la lupa —abajo a la
 * derecha— porque nunca coinciden: o busca o fabrica.
 *
 * Se dibuja quieto y en vertical, y todo el movimiento es un giro alrededor
 * de `eje`, que es la mano. Por eso el mango arranca justo ahí: si el pivote
 * no está en el extremo, el martillo levita en vez de empuñarse.
 *
 * Los ángulos están medidos para que la cabeza no se salga del `viewBox` ni
 * llegue a la boca: a `alzado` la esquina de arriba queda en x≈201 —la boca
 * acaba en 177— y a `golpe` la de la derecha en x≈313, con el borde en 332.
 */
export const MARTILLO = {
  eje: { x: 272, y: 302 },
  mango: "M 272 302 L 272 246",
  grosorMango: 13,
  cabeza: { x: 240, y: 216, ancho: 64, alto: 32, rx: 9 },
  /** Grados. Negativo es hacia atrás: el brazo cargado antes de bajar. */
  alzado: -30,
  golpe: 6,
  /** Segundos por martillazo. Un poco más lento que un martillo de verdad. */
  compas: 0.78,
} as const;
