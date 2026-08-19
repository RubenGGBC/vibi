/* El asistente, paso a paso.
 *
 * Cada paso declara lo que se lee arriba, lo que se pinta en medio y cuánto ha
 * despertado Vibi (`vigilia`, de 0 a 1). Lo demás —el halo, su color, su
 * respiración, el fondo— cuelga de esa sola variable en el CSS, así que aquí
 * no hay animaciones a mano: se mueve un número y la escena se acomoda.
 */
/* Python se llama directamente por el puente de la ventana: no hay servidor,
   ni puerto, ni `fetch`. Los avisos de la instalación vienen al revés, de
   Python a aquí, para que cada línea aparezca en cuanto se genera. */
const api = () => window.pywebview.api;

const escena = document.getElementById("escena");
const titulo = document.getElementById("titulo");
const subtitulo = document.getElementById("subtitulo");
const lienzo = document.getElementById("lienzo");
const rastro = document.getElementById("rastro");
const seguir = document.getElementById("seguir");
const atras = document.getElementById("atras");

let estado = null;
let indice = 0;
const eleccion = { motor: "antigravity", capacidades: {} };

/* ---------- Utilidades de pintado ---------- */

const nodo = (etiqueta, clases, texto) => {
  const el = document.createElement(etiqueta);
  if (clases) el.className = clases;
  if (texto != null) el.textContent = texto;
  return el;
};

function ficha({ estado: marca, simbolo, nombre, texto, extra }) {
  const li = nodo("li", "ficha");
  li.dataset.estado = marca;
  li.append(nodo("span", "ficha-marca", simbolo));
  const cuerpo = nodo("div");
  cuerpo.append(nodo("div", "ficha-nombre", nombre));
  if (texto) cuerpo.append(nodo("p", "ficha-texto", texto));
  if (extra) {
    const p = nodo("p", "ficha-texto");
    p.append(nodo("code", null, extra));
    cuerpo.append(p);
  }
  li.append(cuerpo);
  return li;
}

/* ---------- Los pasos ---------- */

const pasos = [
  {
    clave: "despertar",
    vigilia: 0.08,
    titulo: () => "Vibi está dormida",
    subtitulo: () =>
      `Va a vivir en tu ${estado.sistema.descripcion}, no en la nube. ` +
      `Esto es lo que ha encontrado aquí.`,
    pintar() {
      const lista = nodo("ul", "fichas");
      for (const r of estado.requisitos) {
        lista.append(
          ficha({
            estado: r.encontrado ? "ok" : r.imprescindible ? "falta" : "no-aqui",
            simbolo: r.encontrado ? "✓" : r.imprescindible ? "!" : "–",
            nombre: r.nombre,
            texto: r.encontrado ? "" : r.como_conseguirlo,
            extra: r.encontrado ? r.detalle : "",
          })
        );
      }
      return lista;
    },
    listo: () => estado.se_puede,
    // Un botón apagado sin explicación es lo peor de un instalador: parece que
    // se ha roto. Si falta algo imprescindible, el botón lo dice.
    etiqueta: () => (estado.se_puede ? "Seguir" : "Falta algo de arriba"),
  },

  {
    clave: "cuenta",
    vigilia: 0.28,
    titulo: () => "¿Cómo te llamas?",
    subtitulo: () =>
      "Vibi te llamará así, y con esto entrarás desde el móvil o desde otro " +
      "ordenador de tu malla.",
    pintar() {
      const caja = nodo("div", "campos");
      caja.append(
        campo("usuario", "Tu nombre", "text", "ruben"),
        campo("password", "Una contraseña", "password", ""),
        campo("password2", "Repítela", "password", "")
      );
      const aviso = nodo("p", "aviso");
      aviso.id = "aviso-cuenta";
      caja.append(aviso);
      caja.addEventListener("input", revisarCuenta);
      return caja;
    },
    alEntrar: revisarCuenta,
    listo: () =>
      Boolean(valor("usuario") && valor("password")) && problemaCuenta() === "",
    alSalir() {
      eleccion.usuario = valor("usuario");
      eleccion.password = valor("password");
    },
  },

  {
    clave: "motor",
    vigilia: 0.48,
    titulo: () => "¿Con qué cabeza piensa?",
    subtitulo: () =>
      "Vibi habla con Gemini a través de Antigravity, con tu cuenta de Google. " +
      "Puedes cambiarlo luego desde los ajustes.",
    pintar() {
      const lista = nodo("ul", "fichas");
      for (const m of estado.modelos) {
        const li = nodo("li", "ficha ficha-elegible");
        li.dataset.estado = "ok";
        const etiqueta = nodo("label");
        etiqueta.style.cssText = "display:contents";
        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "modelo";
        radio.value = m.clave;
        radio.checked = m.clave === (eleccion.modelo || modeloPorDefecto());
        radio.addEventListener("change", () => {
          eleccion.modelo = radio.value;
        });
        const cuerpo = nodo("div");
        cuerpo.append(nodo("div", "ficha-nombre", m.nombre));
        cuerpo.append(nodo("p", "ficha-texto", m.descripcion));
        etiqueta.append(radio, cuerpo);
        li.append(etiqueta);
        lista.append(li);
      }
      eleccion.modelo = eleccion.modelo || modeloPorDefecto();
      return lista;
    },
    listo: () => true,
  },

  {
    clave: "capacidades",
    vigilia: 0.68,
    titulo: () => "¿Qué le dejas hacer?",
    subtitulo: () =>
      "Todo esto pasa dentro de tu ordenador. Puedes cambiarlo después, y lo " +
      "que aquí no funcione te dice por qué.",
    pintar() {
      const lista = nodo("ul", "fichas");
      for (const c of estado.capacidades) {
        const li = nodo("li", "ficha ficha-elegible");
        li.dataset.estado = c.disponible ? "ok" : "no-aqui";
        const etiqueta = nodo("label");
        etiqueta.style.cssText = "display:contents";
        const casilla = document.createElement("input");
        casilla.type = "checkbox";
        casilla.disabled = !c.disponible || c.clave === "chat";
        casilla.checked = c.disponible && (c.recomendada || c.clave === "chat");
        eleccion.capacidades[c.clave] = casilla.checked;
        casilla.addEventListener("change", () => {
          eleccion.capacidades[c.clave] = casilla.checked;
        });
        const cuerpo = nodo("div");
        cuerpo.append(nodo("div", "ficha-nombre", c.nombre));
        cuerpo.append(nodo("p", "ficha-texto", c.explicacion));
        if (c.motivo) cuerpo.append(nodo("p", "ficha-texto", c.motivo));
        etiqueta.append(casilla, cuerpo);
        li.append(etiqueta);
        lista.append(li);
      }
      return lista;
    },
    listo: () => true,
    etiqueta: () => "Despertarla",
  },

  {
    clave: "instalando",
    vigilia: 0.86,
    animo: "instalando",
    titulo: () => "Despertándola",
    subtitulo: () => "Esto tarda un par de minutos la primera vez.",
    pintar() {
      const consola = nodo("div", "consola");
      consola.id = "consola";
      return consola;
    },
    alEntrar: instalar,
    listo: () => false,
    ocultarBotones: true,
  },

  {
    clave: "lista",
    vigilia: 1,
    animo: "lista",
    titulo: () => "Vibi está despierta",
    subtitulo: () => "Ya está corriendo en tu ordenador. Puedes hablar con ella.",
    pintar() {
      const caja = nodo("div", "remate");

      const abrir = nodo("button", "boton boton-grande", "Hablar con Vibi");
      abrir.type = "button";
      abrir.addEventListener("click", () => {
        api().abrir_vibi(eleccion.url || "http://127.0.0.1:8000");
      });
      caja.append(abrir);

      caja.append(
        nodo(
          "p",
          null,
          "Arranca sola al encender el ordenador. Si alguna vez la paras, " +
            "vuelve con:"
        )
      );
      caja.append(nodo("code", "orden mono", eleccion.guion || ""));
      return caja;
    },
    listo: () => false,
    ocultarBotones: true,
  },
];

function modeloPorDefecto() {
  const recomendado = estado.modelos.find((m) => m.recomendado);
  return (recomendado || estado.modelos[0]).clave;
}

function campo(id, etiqueta, tipo, marcador) {
  const envoltorio = nodo("label", "campo");
  envoltorio.append(nodo("span", null, etiqueta));
  const entrada = document.createElement("input");
  entrada.id = id;
  entrada.type = tipo;
  entrada.placeholder = marcador;
  entrada.autocomplete = tipo === "password" ? "new-password" : "username";
  envoltorio.append(entrada);
  return envoltorio;
}

const valor = (id) => (document.getElementById(id)?.value || "").trim();

function problemaCuenta() {
  if (!valor("usuario")) return "";
  if (valor("password").length < 8) return "La contraseña necesita ocho caracteres o más.";
  if (valor("password") !== valor("password2")) return "Las dos contraseñas no coinciden.";
  return "";
}

function revisarCuenta() {
  const aviso = document.getElementById("aviso-cuenta");
  // Solo se regaña cuando ya hay algo escrito en la segunda: quejarse de que
  // «no coinciden» mientras aún la estás tecleando es ruido.
  if (aviso) aviso.textContent = valor("password2") ? problemaCuenta() : "";
  const completo = valor("usuario") && valor("password") && !problemaCuenta();
  seguir.disabled = !completo;
}

/* ---------- Instalación ---------- */

/* Python empuja aquí cada paso de la instalación. Global a propósito: es el
   nombre que la ventana llama con `evaluate_js`. */
window.recibirEvento = function (dato) {
  const consola = document.getElementById("consola");
  if (!consola) return;
  const escribir = (texto, clase) => {
    const linea = nodo("div", clase);
    linea.textContent = texto;
    consola.append(linea);
    consola.scrollTop = consola.scrollHeight;
  };

  if (dato.tipo === "paso") {
    const linea = nodo("div");
    linea.append(nodo("b", null, dato.texto));
    consola.append(linea);
    consola.scrollTop = consola.scrollHeight;
  } else if (dato.tipo === "detalle") {
    escribir(dato.texto);
  } else if (dato.tipo === "hecho" && dato.detalle) {
    escribir(dato.detalle);
  } else if (dato.tipo === "resumen") {
    eleccion.guion = dato.guion;
    eleccion.url = dato.url;
  } else if (dato.tipo === "error") {
    escena.dataset.animo = "mal";
    titulo.textContent = "No he podido despertarla";
    subtitulo.textContent =
      "Abajo está lo que ha fallado. Arréglalo y vuelve a intentarlo.";
    escribir(dato.mensaje, "mal");
  } else if (dato.tipo === "listo") {
    setTimeout(() => ir(indice + 1), 700);
  }
};

async function instalar() {
  await api().instalar(eleccion);
}

/* ---------- Navegación ---------- */

function pintarRastro() {
  rastro.replaceChildren();
  pasos.forEach((_, i) => {
    const punto = nodo("li");
    if (i < indice) punto.dataset.hecho = "";
    if (i === indice) punto.dataset.actual = "";
    rastro.append(punto);
  });
}

function ir(nuevo) {
  const paso = pasos[nuevo];
  if (!paso) return;
  if (indice !== nuevo && pasos[indice]?.alSalir) pasos[indice].alSalir();
  indice = nuevo;

  // En la raíz y no en la escena: el fondo lo pinta `body::before`, que es
  // ancestro de la escena y no heredaría nada puesto ahí abajo.
  document.documentElement.style.setProperty("--vigilia", paso.vigilia);
  escena.dataset.animo = paso.animo || "";
  titulo.textContent = paso.titulo();
  subtitulo.textContent = paso.subtitulo();

  lienzo.replaceChildren(paso.pintar());
  // Reinicia la animación de entrada, que si no solo se ve la primera vez.
  lienzo.style.animation = "none";
  void lienzo.offsetWidth;
  lienzo.style.animation = "";

  const ocultos = Boolean(paso.ocultarBotones);
  seguir.hidden = ocultos;
  atras.hidden = ocultos || indice === 0;
  seguir.textContent = paso.etiqueta ? paso.etiqueta() : "Seguir";
  seguir.disabled = !paso.listo();
  pintarRastro();
  paso.alEntrar?.();
}

seguir.addEventListener("click", () => ir(indice + 1));
atras.addEventListener("click", () => ir(indice - 1));

/* ---------- Arranque ---------- */

async function arrancar() {
  try {
    estado = await api().estado();
  } catch (error) {
    lienzo.replaceChildren(
      nodo("p", "aviso", `El instalador no ha podido mirar tu ordenador: ${error}`)
    );
    return;
  }
  ir(0);
}

/* El puente no existe hasta que la ventana lo anuncia, así que arrancar sin
   esperar el aviso deja la pantalla en «Mirando qué hay…» para siempre. Y si
   llegó antes de que este guion cargara, el evento ya no vuelve a dispararse:
   por eso se comprueba también a mano. */
if (window.pywebview && window.pywebview.api) {
  arrancar();
} else {
  window.addEventListener("pywebviewready", arrancar, { once: true });
}
