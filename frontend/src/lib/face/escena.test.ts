import { afterEach, describe, expect, it } from "vitest";

import { cadenciaDe, crearEscenaCara, type FaceScene } from "./escena";
import { SENALES_QUIETAS } from "./modificadores";
import { callarOido, publicarNivelDeVoz } from "./oido";

let escena: FaceScene | null = null;
let contenedor: HTMLElement | null = null;

const montar = (perfil: "web" | "companion" = "companion") => {
  contenedor = document.createElement("div");
  document.body.appendChild(contenedor);
  escena = crearEscenaCara(contenedor, { perfil });
  return { contenedor, escena };
};

/** Deja los muelles asentados: recién montada todo está en movimiento. */
const asentar = (escena: FaceScene, fotogramas = 90) => {
  for (let i = 0; i < fotogramas; i += 1) escena.dibujar(1 / 60);
};

const atributo = (raiz: HTMLElement, selector: string, nombre: string) =>
  raiz.querySelector(selector)?.getAttribute(nombre) ?? "";

const numero = (raiz: HTMLElement, selector: string, nombre: string) =>
  Number(atributo(raiz, selector, nombre));

/** Cuánto sube y baja una lengua de fuego a lo largo de cuatro segundos. */
const amplitudDeLlama = (escena: FaceScene, raiz: HTMLElement, fotogramas = 240) => {
  let minimo = Infinity;
  let maximo = -Infinity;
  for (let i = 0; i < fotogramas; i += 1) {
    escena.dibujar(1 / 60);
    const alto = Number(
      /scale\((-?[\d.]+) (-?[\d.]+)\)/.exec(atributo(raiz, ".vibi-lengua", "transform"))![2],
    );
    minimo = Math.min(minimo, alto);
    maximo = Math.max(maximo, alto);
  }
  return maximo - minimo;
};

afterEach(() => {
  escena?.dispose();
  contenedor?.remove();
  callarOido();
  escena = null;
  contenedor = null;
});

describe("montar la escena", () => {
  it("mete un svg en el contenedor", () => {
    const { contenedor } = montar();
    expect(contenedor.querySelector("svg")).not.toBeNull();
  });

  it("dibuja la cara ya en el primer fotograma", () => {
    // Sin esto se ve un hueco vacío hasta el primer `requestAnimationFrame`.
    const { contenedor } = montar();
    expect(atributo(contenedor, ".vibi-carne", "d")).toMatch(/^M/);
    expect(atributo(contenedor, ".vibi-ojo", "d")).toMatch(/^M/);
  });

  it("recorta el antifaz contra la cabeza en vez de dibujarlo a medida", () => {
    // El antifaz desborda la silueta por todos lados a propósito: lo único que
    // se dibuja de él es por dónde pasa su borde de abajo. Sin el recorte
    // habría que redibujarlo cada vez que se toque el contorno de la cabeza.
    const { contenedor } = montar();
    expect(contenedor.querySelector("clipPath")).not.toBeNull();
    expect(atributo(contenedor, ".vibi-antifaz", "d")).toMatch(/^M/);
    expect(contenedor.querySelector(".vibi-antifaz")?.parentElement?.getAttribute("clip-path"))
      .toMatch(/^url\(#/);
  });

  it("monta el sombrero en dos mitades con la cara entre medias", () => {
    // La copa va detrás y el ala delante, pero son el mismo sombrero: por eso
    // son dos grupos que comparten matriz y no uno solo.
    const { contenedor } = montar();
    const orden = [...contenedor.querySelectorAll("g[class^='vibi-']")].map((n) =>
      n.getAttribute("class"),
    );
    expect(orden.indexOf("vibi-copa")).toBeLessThan(orden.indexOf("vibi-ala"));
    expect(atributo(contenedor, ".vibi-copa", "transform")).toBe(
      atributo(contenedor, ".vibi-ala", "transform"),
    );
  });

  it("da al svg un sistema de coordenadas propio para que escale solo", () => {
    // Con `viewBox` el redimensionado es cosa del navegador, no nuestra.
    const { contenedor } = montar();
    expect(contenedor.querySelector("svg")?.getAttribute("viewBox")).toBeTruthy();
  });

  it("no se anuncia a los lectores de pantalla", () => {
    // Es decoración: lo que Vibi está haciendo se cuenta con texto aparte.
    const { contenedor } = montar();
    expect(contenedor.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("no escribe NaN en ningún atributo", () => {
    const { contenedor, escena } = montar();
    escena.setSenales({ ...SENALES_QUIETAS, cadencia: 33, pasos: 9, retrasoCanal: 4200 });
    asentar(escena, 30);
    const todo = contenedor.innerHTML;
    expect(todo).not.toMatch(/NaN/);
  });
});

describe("cambiar de cara", () => {
  it("cambia la forma de los ojos", () => {
    const { contenedor, escena } = montar();
    asentar(escena);
    const antes = atributo(contenedor, ".vibi-ojo", "d");
    escena.setState("recelo");
    asentar(escena, 30);
    expect(atributo(contenedor, ".vibi-ojo", "d")).not.toBe(antes);
  });

  it("le pone a cada estado la silueta que dice su gesto", () => {
    // Mirar la ventana no basta para esto: a 320 px una rendija y una píldora
    // se distinguen mal, y un estado apuntando a la forma equivocada no da
    // ningún error. Los números del trazado van en el espacio del ojo, así que
    // la caja que ocupan **es** la forma.
    const caja = (d: string) => {
      const n = d.match(/-?\d+\.\d+/g)!.map(Number);
      const xs = n.filter((_, i) => i % 2 === 0);
      const ys = n.filter((_, i) => i % 2 === 1);
      return {
        ancho: Math.max(...xs) - Math.min(...xs),
        alto: Math.max(...ys) - Math.min(...ys),
      };
    };
    const { contenedor, escena } = montar();

    escena.setState("offline");
    asentar(escena, 90);
    const rendija = caja(atributo(contenedor, ".vibi-ojo", "d"));
    expect(rendija.ancho, "la rendija va tumbada").toBeGreaterThan(rendija.alto * 2);

    escena.setState("idle");
    asentar(escena, 90);
    const pildora = caja(atributo(contenedor, ".vibi-ojo", "d"));
    expect(pildora.alto, "la píldora va de pie").toBeGreaterThan(pildora.ancho);

    escena.setState("hacking");
    asentar(escena, 90);
    const guion = caja(atributo(contenedor, ".vibi-ojo", "d"));
    expect(guion.ancho, "el guion del `->` va tumbado").toBeGreaterThan(guion.alto * 2);

    escena.setState("recelo");
    asentar(escena, 90);
    const cuna = caja(atributo(contenedor, ".vibi-ojo", "d"));
    expect(cuna.ancho, "la cuña del recelo es mucho más ancha que la píldora")
      .toBeGreaterThan(pildora.ancho * 1.8);
  });

  it("le devuelve a la cuña el grosor que en la lámina ponía el trazo", () => {
    // El contorno da la línea media, no el bulto. Sin este perfilado la cuña
    // del recelo sale un tercio más flaca que la dibujada, y es un fallo que no
    // se ve comparando de memoria: hace falta poner las dos al mismo tamaño.
    const { contenedor, escena } = montar();
    asentar(escena, 60);
    expect(numero(contenedor, ".vibi-ojo", "stroke-width")).toBeCloseTo(0, 1);
    escena.setState("recelo");
    asentar(escena, 60);
    expect(numero(contenedor, ".vibi-ojo", "stroke-width")).toBeGreaterThan(5);
    // Y vuelve solo: si se quedara puesto, la píldora saldría hinchada.
    escena.setState("idle");
    asentar(escena, 60);
    expect(numero(contenedor, ".vibi-ojo", "stroke-width")).toBeCloseTo(0, 1);
  });

  it("recelar deja un ojo distinto del otro", () => {
    const { contenedor, escena } = montar();
    escena.setState("recelo");
    asentar(escena, 30);
    const ojos = [...contenedor.querySelectorAll(".vibi-ojo")].map((n) => n.getAttribute("d"));
    expect(ojos[0]).not.toBe(ojos[1]);
  });

  it("aplasta la cabeza al cambiar, y la deja volver", () => {
    // La transición entre caras es un empujón a un muelle, no una animación
    // escrita: por eso hay una sola para las treinta y dos combinaciones.
    const { contenedor, escena } = montar();
    asentar(escena);
    escena.dibujar(1 / 60);
    const quieta = atributo(contenedor, ".vibi-cuerpo", "transform");
    escena.setState("logro");
    escena.dibujar(1 / 60);
    expect(atributo(contenedor, ".vibi-cuerpo", "transform")).not.toBe(quieta);
    // Y el muelle vuelve solo: sin esto la cara se quedaría aplastada.
    asentar(escena, 240);
    const escala = /scale\((-?[\d.]+) (-?[\d.]+)\)/.exec(
      atributo(contenedor, ".vibi-cuerpo", "transform"),
    );
    expect(Number(escala![1])).toBeCloseTo(1, 2);
    expect(Number(escala![2])).toBeCloseTo(1, 2);
  });

  it("el sombrero llega tarde al cabezazo", () => {
    // El movimiento secundario: la chistera no va pegada a la cabeza, la
    // persigue con un muelle más blando. Si compartieran matriz, el sombrero
    // no aportaría nada y habría que animarlo a mano en cada pose.
    const { contenedor, escena } = montar();
    asentar(escena);
    escena.setState("logro");
    escena.dibujar(1 / 60);
    escena.dibujar(1 / 60);
    const sombrero = atributo(contenedor, ".vibi-copa", "transform");
    expect(sombrero).not.toBe(atributo(contenedor, ".vibi-cuerpo", "transform"));
    const desfase = /translate\((-?[\d.]+) (-?[\d.]+)\)/.exec(sombrero);
    expect(Math.abs(Number(desfase![2]))).toBeGreaterThan(0);
  });

  it("deja la interrogación puesta el rato suficiente para leerla", () => {
    // Asomar y desaparecer en el acto no cuenta nada, y encima a media
    // opacidad se le ve la sombra por debajo y sale granate en vez de roja.
    const { contenedor, escena } = montar();
    escena.setState("thinking");
    asentar(escena, 40);
    let opacas = 0;
    for (let i = 0; i < 156; i += 1) {
      escena.dibujar(1 / 60);
      if (numero(contenedor, ".vibi-interrogacion", "opacity") > 0.95) opacas += 1;
    }
    // Del ciclo de 2,6 s tiene que estar del todo opaca al menos un tercio.
    expect(opacas).toBeGreaterThan(52);
  });

  it("enciende y apaga los complementos", () => {
    const { contenedor, escena } = montar();
    escena.setState("searching");
    asentar(escena, 40);
    expect(numero(contenedor, ".vibi-lupa", "opacity")).toBeGreaterThan(0.9);
    expect(numero(contenedor, ".vibi-onda", "opacity")).toBeLessThan(0.1);
    escena.setState("speaking");
    asentar(escena, 40);
    expect(numero(contenedor, ".vibi-lupa", "opacity")).toBeLessThan(0.1);
    expect(numero(contenedor, ".vibi-onda", "opacity")).toBeGreaterThan(0.9);
  });
});

describe("lo que la cara escucha", () => {
  it("aviva el fuego con lo que se te oye", () => {
    // La prueba de que esto no es una animación en bucle: el mismo estado, el
    // mismo gesto, y el fuego moviéndose más porque le estás hablando.
    //
    // Se mide la AMPLITUD del titileo a lo largo de unos segundos y no un
    // fotograma suelto: la llama oscila sola, así que dos capturas cualesquiera
    // salen distintas y no probarían nada.
    const { contenedor, escena } = montar();
    asentar(escena, 30);
    const callado = amplitudDeLlama(escena, contenedor);
    publicarNivelDeVoz(0.3);
    expect(amplitudDeLlama(escena, contenedor)).toBeGreaterThan(callado);
  });

  it("aviva el fuego con el caudal de tokens", () => {
    const { contenedor, escena } = montar();
    escena.setState("speaking");
    asentar(escena, 30);
    const quieto = amplitudDeLlama(escena, contenedor);
    escena.setSenales({ ...SENALES_QUIETAS, cadencia: 40 });
    expect(amplitudDeLlama(escena, contenedor)).toBeGreaterThan(quieto);
  });

  it("apaga el fuego cuando no hay canal", () => {
    // Y esto es lo contrario: la opacidad no cuenta el ardor entero, solo
    // separa lo que arde de lo que está apagado del todo.
    const { contenedor, escena } = montar();
    asentar(escena, 30);
    const reposo = numero(contenedor, ".vibi-llama", "opacity");
    escena.setState("offline");
    asentar(escena, 30);
    expect(numero(contenedor, ".vibi-llama", "opacity")).toBeLessThan(reposo * 0.5);
  });

  it("mueve la onda con el micrófono", () => {
    const { contenedor, escena } = montar();
    escena.setState("listening");
    asentar(escena, 40);
    const quieta = atributo(contenedor, ".vibi-barra", "transform");
    publicarNivelDeVoz(0.3);
    escena.dibujar(1 / 60);
    expect(atributo(contenedor, ".vibi-barra", "transform")).not.toBe(quieta);
  });

  it("acepta señales y puntero sin romperse", () => {
    const { escena } = montar();
    expect(() => {
      escena.setSenales({ ...SENALES_QUIETAS, pasos: 6 });
      escena.setPointer(0.5, -0.2);
      escena.dibujar(1 / 60);
      escena.clearPointer();
    }).not.toThrow();
  });

  it("solo sigue al cursor en el companion", () => {
    // En la PWA la cara comparte página con el resto, y seguir el cursor la
    // volvería inquieta sin motivo.
    const { contenedor, escena } = montar("web");
    asentar(escena);
    const antes = atributo(contenedor, ".vibi-ojo", "transform");
    escena.setPointer(1, 1);
    escena.dibujar(1 / 60);
    const despues = atributo(contenedor, ".vibi-ojo", "transform");
    // La mirada suelta sigue derivando, así que se compara el salto: seguir al
    // cursor de esquina a esquina movería el ojo mucho más que una sacada.
    const x = (t: string) => Number(/translate\((-?[\d.]+)/.exec(t)![1]);
    expect(Math.abs(x(despues) - x(antes))).toBeLessThan(3);
  });
});

describe("desmontar", () => {
  it("deja el contenedor limpio", () => {
    const { contenedor, escena } = montar();
    escena.dispose();
    expect(contenedor.querySelector("svg")).toBeNull();
  });

  it("aguanta que le sigan hablando después", () => {
    // React puede entregar un cambio de estado entre el desmontaje y la
    // limpieza del efecto.
    const { escena } = montar();
    escena.dispose();
    expect(() => {
      escena.setState("thinking");
      escena.dibujar(1 / 60);
      escena.resize();
      escena.dispose();
    }).not.toThrow();
  });
});

describe("la cadencia del repintado", () => {
  it("repinta menos veces por segundo cuando no hay nada que contar", () => {
    // El bucle iba a sesenta pasara lo que pasara. Medido en el companion,
    // eso costaba el 44% de un núcleo dibujando una cara que en reposo solo
    // parpadea. Un intervalo mayor significa menos fotogramas por segundo.
    expect(cadenciaDe("idle", false)).toBeGreaterThan(cadenciaDe("working", false));
    expect(cadenciaDe("offline", false)).toBeGreaterThan(cadenciaDe("thinking", false));
    // Vigilar dura horas: es el que más se agradece a media cadencia.
    expect(cadenciaDe("vigilando", false)).toBeGreaterThan(cadenciaDe("searching", false));
  });

  it("vuelve a la cadencia viva mientras sigue al cursor", () => {
    // Seguir al puntero a veinte por segundo se ve a tirones: ahí el
    // movimiento es continuo y lo está provocando el usuario.
    expect(cadenciaDe("idle", true)).toBe(cadenciaDe("working", false));
  });
});
