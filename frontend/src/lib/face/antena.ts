import { avanzarMuelle, crearMuelle, fijarMuelle, type Muelle } from "../faceMotion";
import type { Point as Punto2D } from "./bloub/shape";

/**
 * La antena: tallo y bola, colgando de lo alto de la cabeza.
 *
 * Es la pieza que el referente no tiene, y la que evita que esto sea un calco.
 * bloub tiene dos canales, la silueta y la mirada; la antena es un tercero, y
 * uno **físico**: no se anima, se arrastra. Cada movimiento del cuerpo la mueve
 * gratis porque va por detrás con retraso, así que una pose no tiene que
 * acordarse de ella para que cuente algo.
 *
 * Son dos articulaciones —base, codo, bola— y cada coordenada del codo y de la
 * bola es un muelle que persigue su posición ideal. La amortiguación va por
 * debajo de la crítica a propósito: pasarse de frenada y volver es de donde
 * sale la sensación de que hay peso en la punta.
 */

/** Del anclaje al codo, en unidades de cabeza. */
const LARGO_TALLO = 0.42;

/** Del codo a la bola. */
const LARGO_PUNTA = 0.34;

/** Lo que mide entera y estirada. Las poses lo usan para colocar cosas. */
export const LARGO_ANTENA = LARGO_TALLO + LARGO_PUNTA;

/** Por debajo de la crítica (`2·√rigidez`): rebota un poco al llegar. */
const FACTOR_AMORTIGUACION = 1.55;

/**
 * El paso más largo que se le pasa al muelle.
 *
 * `avanzarMuelle` trocea el delta, pero corta en ocho subpasos: con un salto de
 * cuatro segundos —volver a una ventana minimizada— cada subpaso sale de medio
 * segundo y la integración de Euler se dispara al infinito. Recortar aquí es
 * más honesto que subir el tope de subpasos: nadie quiere ver cuatro segundos
 * de antena recuperados de golpe, quiere que esté donde toca.
 */
const PASO_MAXIMO = 0.05;

export interface EstadoAntena {
  /** 1 estirada, 0 recogida del todo contra la cabeza. */
  largo: number;
  /** Cuánto tira de la posición ideal. Bajo = se arrastra mucho. */
  rigidez: number;
  /** Grados que se dobla la punta. Positivo hacia la derecha de la pantalla. */
  curva: number;
  /** Radio de la bola, en unidades de cabeza. */
  radioBola: number;
  /** La bola se desprende del tallo: pensar la pone a orbitar, alerta la baja. */
  bolaSuelta: boolean;
  /** Adónde va la bola suelta, en coordenadas de cabeza. */
  bolaDestino?: Punto2D;
}

export const ANTENA_REPOSO: EstadoAntena = {
  largo: 1,
  rigidez: 130,
  curva: 0,
  radioBola: 0.13,
  bolaSuelta: false,
};

export interface FormaAntena {
  base: Punto2D;
  codo: Punto2D;
  bola: Punto2D;
  radioBola: number;
}

export interface Antena {
  /** Avanza la física un paso y devuelve dónde ha quedado. */
  avanzar(estado: EstadoAntena, anclaje: Punto2D, delta: number): FormaAntena;
  /** La planta ya asentada, sin recorrido. Para el montaje inicial. */
  fijar(estado: EstadoAntena, anclaje: Punto2D): FormaAntena;
}

const rad = (grados: number): number => (grados * Math.PI) / 180;

/** Adónde querrían ir el codo y la bola si no hubiera inercia de por medio. */
function destinos(estado: EstadoAntena, anclaje: Punto2D): { codo: Punto2D; bola: Punto2D } {
  const curva = rad(estado.curva);
  // El codo se dobla la mitad que la punta: así el tallo describe un arco en
  // vez de un codo de fontanería.
  const codo = {
    x: anclaje.x + Math.sin(curva * 0.5) * LARGO_TALLO * estado.largo,
    y: anclaje.y - Math.cos(curva * 0.5) * LARGO_TALLO * estado.largo,
  };
  const bola =
    estado.bolaSuelta && estado.bolaDestino
      ? estado.bolaDestino
      : {
          x: codo.x + Math.sin(curva) * LARGO_PUNTA * estado.largo,
          y: codo.y - Math.cos(curva) * LARGO_PUNTA * estado.largo,
        };
  return { codo, bola };
}

export function crearAntena(): Antena {
  const codoX: Muelle = crearMuelle(0);
  const codoY: Muelle = crearMuelle(0);
  const bolaX: Muelle = crearMuelle(0);
  const bolaY: Muelle = crearMuelle(0);

  const forma = (estado: EstadoAntena, anclaje: Punto2D): FormaAntena => ({
    base: anclaje,
    codo: { x: codoX.valor, y: codoY.valor },
    bola: { x: bolaX.valor, y: bolaY.valor },
    radioBola: estado.radioBola,
  });

  return {
    avanzar(estado, anclaje, delta) {
      const paso = Math.min(delta, PASO_MAXIMO);
      const ideal = destinos(estado, anclaje);
      const amortiguacion = FACTOR_AMORTIGUACION * Math.sqrt(estado.rigidez);
      avanzarMuelle(codoX, ideal.codo.x, paso, estado.rigidez, amortiguacion);
      avanzarMuelle(codoY, ideal.codo.y, paso, estado.rigidez, amortiguacion);
      // La bola va más blanda que el codo: es la que tiene que colear.
      const rigidezBola = estado.rigidez * 0.62;
      const amortiguacionBola = FACTOR_AMORTIGUACION * Math.sqrt(rigidezBola);
      avanzarMuelle(bolaX, ideal.bola.x, paso, rigidezBola, amortiguacionBola);
      avanzarMuelle(bolaY, ideal.bola.y, paso, rigidezBola, amortiguacionBola);
      return forma(estado, anclaje);
    },

    fijar(estado, anclaje) {
      const ideal = destinos(estado, anclaje);
      fijarMuelle(codoX, ideal.codo.x);
      fijarMuelle(codoY, ideal.codo.y);
      fijarMuelle(bolaX, ideal.bola.x);
      fijarMuelle(bolaY, ideal.bola.y);
      return forma(estado, anclaje);
    },
  };
}
