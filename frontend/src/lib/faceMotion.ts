/**
 * La aritmética del movimiento de la cara, sin Three.js y sin DOM.
 *
 * `face3d` se encarga de la escena; aquí vive lo que se puede razonar a solas:
 * cómo llega un valor a su destino, cada cuánto merece la pena dibujar y
 * durante cuánto tiempo cuenta el ratón como algo que Vibi está mirando.
 */

export interface Muelle {
  valor: number;
  velocidad: number;
}

export const crearMuelle = (valor: number): Muelle => ({ valor, velocidad: 0 });

/**
 * Avanza el muelle hacia `destino` integrando la aceleración.
 *
 * `rigidez` es cuánto tira del destino y `amortiguacion` cuánto frena. Con
 * `amortiguacion = 2 * sqrt(rigidez)` llega justo sin pasarse; por debajo se
 * pasa de frenada y vuelve, que es de donde sale la sensación de que hay peso
 * detrás del gesto.
 */
export function avanzarMuelle(
  muelle: Muelle,
  destino: number,
  delta: number,
  rigidez: number,
  amortiguacion: number,
): number {
  // Un solo paso de Euler con un delta grande —volver a una ventana que estuvo
  // oculta— manda el muelle al infinito. Trocearlo lo mantiene estable.
  const pasos = Math.max(1, Math.min(8, Math.ceil(delta / 0.016)));
  const h = delta / pasos;
  for (let i = 0; i < pasos; i += 1) {
    const aceleracion =
      (destino - muelle.valor) * rigidez - muelle.velocidad * amortiguacion;
    muelle.velocidad += aceleracion * h;
    muelle.valor += muelle.velocidad * h;
  }
  return muelle.valor;
}

/** Deja el muelle plantado en el destino, sin recorrido ni inercia. */
export function fijarMuelle(muelle: Muelle, valor: number): number {
  muelle.valor = valor;
  muelle.velocidad = 0;
  return valor;
}

export interface Ritmo {
  /** `true` si toca dibujar en este instante (segundos). */
  debeDibujar(ahora: number, activo: boolean): boolean;
}

/**
 * Reparte los fotogramas entre dos cadencias. La ventana del companion se
 * esconde entre conversación y conversación, así que no hay que ahorrar para
 * todo el día; lo que se evita es tener la GPU dibujando a tope una cara que
 * está quieta esperando a que le hablen.
 */
export function crearRitmo(activoFps: number, reposoFps: number): Ritmo {
  let ultimo = Number.NEGATIVE_INFINITY;
  return {
    debeDibujar(ahora, activo) {
      // El margen absorbe el jitter del vsync: sin él un objetivo de 30 fps
      // sobre una pantalla de 60 acaba dibujando a 20.
      const intervalo = 1 / (activo ? activoFps : reposoFps) - 0.004;
      if (ahora - ultimo < intervalo) return false;
      ultimo = ahora;
      return true;
    },
  };
}

export interface Punto {
  x: number;
  y: number;
}

export interface SeguimientoPuntero {
  apuntar(x: number, y: number): void;
  soltar(): void;
  /** El punto que hay que mirar, o `null` si toca volver a la mirada suelta. */
  avanzar(delta: number): Punto | null;
  readonly activo: boolean;
}

/**
 * Recuerda dónde estaba el ratón durante `gracia` segundos. El olvido importa:
 * sin él, dejar el cursor parado encima dejaría a Vibi clavada mirando a un
 * punto muerto en vez de volver a su deriva.
 */
export function crearSeguimientoPuntero(gracia = 1.6): SeguimientoPuntero {
  let objetivo: Punto | null = null;
  let restante = 0;
  return {
    apuntar(x, y) {
      objetivo = { x, y };
      restante = gracia;
    },
    soltar() {
      objetivo = null;
      restante = 0;
    },
    avanzar(delta) {
      if (!objetivo) return null;
      restante -= delta;
      if (restante <= 0) {
        objetivo = null;
        return null;
      }
      return objetivo;
    },
    get activo() {
      return objetivo !== null;
    },
  };
}

/** Recorta un valor al rango dado. */
export const acotar = (valor: number, minimo: number, maximo: number): number =>
  Math.min(maximo, Math.max(minimo, valor));

/**
 * Curva de un gesto suelto: sube de 0 a 1 y vuelve a 0 a lo largo de `avance`
 * (0..1), con la subida más rápida que la bajada. Sirve para el estiramiento y
 * cualquier otro tic que empiece y termine donde estaba.
 */
export function pulso(avance: number): number {
  if (avance <= 0 || avance >= 1) return 0;
  const forma = avance < 0.35 ? avance / 0.35 : 1 - (avance - 0.35) / 0.65;
  // Coseno elevado: quita las esquinas que deja la rampa lineal.
  return 0.5 - Math.cos(Math.PI * forma) * 0.5;
}
