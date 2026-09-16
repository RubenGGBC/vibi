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
const APARIENCIA_ORIGINAL = {
  color_cara: "#FFFFFF",
  color_antifaz: "#0C0714",
  color_sombrero: "#F4121B",
};
const PALETAS = [
  { nombre: "Roja", cara: "#FFF8F5", antifaz: "#130A18", sombrero: "#F4121B" },
  { nombre: "Verde", cara: "#EFFFF5", antifaz: "#09251B", sombrero: "#18C878" },
  { nombre: "Azul", cara: "#EEF6FF", antifaz: "#071B3D", sombrero: "#2488FF" },
  { nombre: "Amarilla", cara: "#FFF9DD", antifaz: "#2D2104", sombrero: "#F5C518" },
];
const eleccion = {
  motor: "antigravity",
  capacidades: {},
  apariencia: { ...APARIENCIA_ORIGINAL },
  entrevista: {},
};

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
    vigilia: 0.42,
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
    clave: "identidad",
    vigilia: 0.55,
    titulo: () => "Hazla tuya",
    subtitulo: () =>
      "En un equipo, estos colores distinguen tu Vibi de las demás. Puedes usar cualquier color y cambiarlo luego.",
    pintar() {
      const caja = nodo("div", "identidad");
      const preview = vistaVibiReal();

      const controles = nodo("div", "identidad-controles");
      const presets = nodo("div", "paletas");
      for (const paleta of PALETAS) {
        const boton = nodo("button", "paleta");
        boton.type = "button";
        boton.title = paleta.nombre;
        boton.setAttribute("aria-label", `Paleta ${paleta.nombre}`);
        boton.style.setProperty("--p-cara", paleta.cara);
        boton.style.setProperty("--p-antifaz", paleta.antifaz);
        boton.style.setProperty("--p-sombrero", paleta.sombrero);
        boton.append(nodo("i"), nodo("i"), nodo("i"));
        boton.addEventListener("click", () => {
          eleccion.apariencia = {
            color_cara: paleta.cara,
            color_antifaz: paleta.antifaz,
            color_sombrero: paleta.sombrero,
          };
          sincronizarColores();
        });
        presets.append(boton);
      }
      controles.append(nodo("p", "identidad-etiqueta", "Paletas rápidas"), presets);
      controles.append(
        selectorColor("color_cara", "Cara y ojos"),
        selectorColor("color_antifaz", "Antifaz"),
        selectorColor("color_sombrero", "Sombrero")
      );
      caja.append(preview, controles);
      requestAnimationFrame(sincronizarColores);
      return caja;
    },
    listo: () => true,
  },

  {
    clave: "entrevista",
    vigilia: 0.67,
    titulo: () => "Antes de empezar, cuéntame de ti",
    subtitulo: () =>
      "Una frase por pregunta basta. Esto crea tu primer perfil y se puede corregir después.",
    pintar() {
      const caja = nodo("div", "entrevista-instalador");
      caja.append(
        pregunta("uso", "¿Para qué vas a usar Vibi?", "Programar, estudiar, organizar proyectos…"),
        pregunta("espera", "¿Qué esperas de ella?", "Que sea breve, que investigue antes de preguntar…"),
        pregunta("delegar", "¿Qué te gustaría delegar?", "Resúmenes, pruebas, seguimiento…"),
        pregunta("libre", "¿Qué te interesa fuera del trabajo?", "Música, fotografía, deporte…"),
        pregunta("forma", "¿Cómo eres trabajando?", "Directo, visual, nocturno, metódico…")
      );
      caja.addEventListener("input", revisarEntrevista);
      return caja;
    },
    alEntrar: revisarEntrevista,
    listo: () => Boolean(valor("entrevista-uso")),
    alSalir() {
      for (const clave of ["uso", "espera", "delegar", "libre", "forma"]) {
        eleccion.entrevista[clave] = valor(`entrevista-${clave}`);
      }
    },
  },

  {
    clave: "capacidades",
    vigilia: 0.76,
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

/** El SVG exacto del companion de escritorio, quieto y sin depender de React. */
function vistaVibiReal() {
  const preview = nodo("div", "vibi-preview");
  preview.id = "vibi-preview";
  preview.innerHTML = `
    <svg class="vibi-preview-svg companion-vibi-svg" viewBox="0 0 420 360" aria-hidden="true">
      <defs>
        <linearGradient id="installer-vibi-sombrero" x1="0" y1="0" x2=".8" y2="1">
          <stop offset="0" stop-color="var(--sombrero)" />
          <stop offset="1" stop-color="var(--sombrero-sombra)" />
        </linearGradient>
        <linearGradient id="installer-vibi-fuego" x1="0" y1="1" x2=".8" y2="0">
          <stop offset="0" stop-color="var(--sombrero-sombra)" />
          <stop offset="1" stop-color="var(--sombrero)" />
        </linearGradient>
      </defs>
      <g class="vibi-preview-figura companion-vibi-figure">
        <g class="companion-vibi-body">
          <path d="M103 232 C136 208 194 194 248 202 C286 207 309 229 307 259 C305 286 282 318 252 334 C241 340 231 345 223 348 C185 343 143 324 116 301 C96 285 91 252 103 232 Z" fill="var(--antifaz)" />
          <path class="companion-vibi-white-silhouette" fill="var(--cara)" fill-rule="evenodd" clip-rule="evenodd" d="M354 169.757 C354 172.358 348.192 177.356 341.455 180.553 C333.684 184.241 329 188.712 329 192.442 C329 195.212 325.687 199.647 322.974 200.508 C321.386 201.012 320.994 202.050 320.968 205.817 C320.951 208.393 320.276 211.374 319.468 212.441 C318.661 213.509 318 215.646 318 217.191 C318 220.791 316.428 220.828 315.516 217.250 C314.821 214.524 314.794 214.542 312.382 219.262 C309.614 224.680 303.634 229.483 297.649 231.094 C294.384 231.974 292.977 231.882 290.330 230.620 C282.338 226.809 285.687 212.317 297.602 199.151 C300.706 195.720 303.052 192.719 302.815 192.482 C301.855 191.522 285.899 205.234 281.084 211.157 C274.818 218.864 269.542 229.075 268.007 236.465 L266.868 241.954 270.830 245.727 C278.044 252.597 278.574 263.125 272.349 275.937 C266.168 288.658 246.202 302.985 236.506 301.656 C232.908 301.163 231.730 301.543 227.473 304.569 C224.780 306.484 219.718 308.933 216.224 310.012 C203.396 313.975 183.130 314.887 175.123 311.863 C173.680 311.319 171.301 309.729 169.835 308.331 C167.363 305.973 166.903 305.877 163.482 307.006 C161.342 307.712 158.080 307.949 155.709 307.569 C150.114 306.675 140.686 301.476 134.578 295.917 C128.194 290.108 123.645 288.480 118.024 289.994 L113.918 291.099 119.692 297.675 C130.588 310.087 143.686 319.619 161.348 327.992 C181.282 337.441 204.632 344.457 220 345.614 C227.293 346.163 227.663 346.079 233.393 342.576 C253.840 330.077 274.868 305.030 280.892 286 C284.489 274.638 285.146 273.461 289.921 269.847 C292.353 268.006 294.547 265.825 294.796 265 C295.162 263.789 294.994 263.741 293.925 264.750 C292.241 266.339 287.768 266.368 286.200 264.800 C284.473 263.073 284.714 261.155 287.378 255.435 C290.808 248.068 294.821 243.997 306.450 236.081 C317.716 228.412 324.356 221.471 321.908 219.923 C321.134 219.433 320.126 218.900 319.669 218.739 C319.211 218.578 319.531 217.108 320.379 215.473 C321.227 213.838 322.172 211.262 322.479 209.750 C322.808 208.131 323.695 207 324.636 207 C325.749 207 326.072 207.616 325.703 209.029 C325.220 210.875 325.502 210.999 328.836 210.396 C333.342 209.580 336.986 207.796 339.132 205.352 C342.523 201.491 345.899 192.701 342.800 195.800 C339.340 199.260 336.789 194.243 339.420 189.155 C340.290 187.472 343.140 184.628 345.751 182.835 C348.363 181.043 351.265 178.659 352.201 177.538 C354.064 175.305 355.539 170.206 354.595 169.262 C354.268 168.934 354 169.157 354 169.757" />
          <g class="vibi-preview-llama" fill="url(#installer-vibi-fuego)">
            <path d="M299.996 265.504 C298.707 266.877 297.139 268 296.514 268 C294.569 268 287.558 271.723 285.858 273.658 C284.382 275.338 280.709 286.042 281.378 286.712 C282.057 287.391 294.443 275.272 298.626 269.837 C303.334 263.718 304.177 261.054 299.996 265.504" />
            <path d="M318.669 239.657 C316.632 243.572 313.418 246.320 307.283 249.390 C300.743 252.662 299.637 252.679 300.245 249.500 C300.508 248.125 300.276 247 299.730 247 C299.184 247 296.810 248.927 294.455 251.282 C291.586 254.150 289.939 256.808 289.466 259.329 C289.078 261.399 289.041 263.374 289.384 263.717 C290.538 264.872 300.095 262.029 303.314 259.574 C305.067 258.237 308.565 256.258 311.086 255.178 C314.336 253.784 315.962 252.382 316.674 250.356 C320.893 238.366 321.761 233.713 318.669 239.657" />
            <path d="M319.207 182.445 C311.769 187.064 309.127 189.808 308.403 193.665 C307.573 198.091 302.466 205.116 300.598 204.399 C299.665 204.041 298.256 205.413 296.525 208.367 C294.553 211.732 293.958 213.954 294.190 217.091 C294.496 221.252 294.545 221.301 298.500 221.460 C305.227 221.729 308.435 219.807 312.902 212.833 C317.312 205.948 318.007 203.142 315.250 203.361 C313.180 203.525 312.512 200.413 313.494 195.179 C313.956 192.716 315.829 189.953 319.581 186.202 C322.561 183.221 325 180.382 325 179.891 C325 178.771 325.431 178.581 319.207 182.445" />
          </g>
          <g class="companion-vibi-hat" fill="url(#installer-vibi-sombrero)">
            <path d="M239 33.618 C212.920 35.977 177.265 45.238 151 56.477 C122.317 68.750 94.486 87.053 78.751 103.990 C67.157 116.469 62.378 127.235 66.570 131.427 C69.283 134.141 73.159 134.393 84.122 132.569 C91.795 131.293 95.300 131.090 96.702 131.840 C100.270 133.750 111.589 146.572 117.221 155.085 C120.284 159.713 125.697 169.350 129.251 176.500 C134.919 187.905 138.613 196.713 149.696 225.250 C151.138 228.963 152.492 232 152.704 232 C153.310 232 166.469 222.929 178 214.562 C192.312 204.178 215.111 187.833 217.840 186 C220.023 184.534 220.039 184.386 218.539 179.500 C217.695 176.750 215.991 169.550 214.752 163.500 C212.744 153.691 212.506 149.685 212.556 126.500 C212.608 102.572 212.824 99.427 215.260 87.037 C216.716 79.632 217.775 73.441 217.613 73.280 C216.518 72.184 182.064 85.388 169.783 91.610 C162.062 95.522 162.024 94.329 169.716 89.541 C191.513 75.977 214.467 65.022 239 56.476 C250.162 52.588 256.182 50.796 270.753 47.023 C273.365 46.346 275.634 44.962 276.634 43.435 C278.152 41.119 278.141 40.813 276.468 38.964 C275.480 37.873 272.383 36.296 269.586 35.461 C264.417 33.916 247.184 32.878 239 33.618" />
            <path d="M230.074 68.824 L224.648 70.527 222.404 81.013 C219.255 95.737 217.997 108.558 218.020 125.711 C218.046 145.433 220.805 165.465 225.024 176.562 C226.067 179.307 227.117 179.069 231.871 175.008 L234.243 172.983 231.684 162.741 C227.670 146.670 226.679 136.444 227.303 117.500 C227.889 99.713 229.939 87.056 234.390 73.750 C235.631 70.037 236.389 67.027 236.074 67.061 C235.758 67.095 233.058 67.888 230.074 68.824" fill="url(#installer-vibi-fuego)" />
            <path d="M302.500 164.642 C287.536 167.804 267.669 175.255 249.500 184.519 C239.600 189.567 228.912 195.158 225.750 196.944 C219.700 200.360 217.835 199.678 223.058 195.959 C228.081 192.382 225.685 192.630 218.045 196.477 C200.305 205.411 181.818 217.269 155 236.914 C145.925 243.562 134.675 250.981 130 253.402 C121.382 257.864 111.645 261.311 110.603 260.270 C110.289 259.956 113.523 257.728 117.789 255.318 C122.055 252.909 126.885 249.843 128.523 248.505 L131.500 246.072 127.700 246.036 C117.338 245.938 112.652 237.796 119.029 230.969 C120.696 229.185 121.825 227.492 121.540 227.207 C120.709 226.375 102.045 228.899 92.937 231.074 C88.345 232.171 80.517 235.012 75.544 237.387 C61.114 244.279 52.726 253.215 51.426 263.081 C50.217 272.255 57.592 280.153 70.460 283.466 C78.709 285.589 92.031 285.425 101.090 283.089 C122 277.697 135.834 269.586 197.500 226.559 C222.280 209.269 236.486 200.630 254.500 191.897 C278.969 180.034 300.188 173.170 315.213 172.256 C327.999 171.479 332.493 174.095 330.541 181.178 C329.964 183.272 330.151 183.206 332.448 180.500 C333.849 178.850 335.487 176.020 336.088 174.212 C336.980 171.528 336.874 170.457 335.512 168.378 C334.595 166.978 332.319 165.196 330.454 164.416 C326.056 162.579 311.717 162.695 302.500 164.642" />
          </g>
          <g class="vibi-preview-ojos" fill="var(--cara)">
            <path transform="translate(174 281)" d="M-6.341 -17.946 C-10.209 -14.904 -11.379 -9.711 -10.520 0.603 C-9.838 8.789 -9.552 9.648 -6.493 12.707 C-1.780 17.420 2.661 17.289 7.034 12.308 L10.276 8.617 9.628 -1.260 C9.267 -6.778 8.326 -12.403 7.496 -14.007 C4.404 -19.987 -1.581 -21.691 -6.341 -17.946" />
            <path transform="translate(234 274)" d="M-5.119 -18.497 C-10.394 -15.630 -12.142 -7.183 -10.070 5.439 C-9.466 9.118 -8.457 11.096 -6.114 13.189 C-1.890 16.964 1.402 16.798 5.600 12.600 C8.999 9.201 9 9.198 9 -0.499 C9 -11.561 7.433 -16.207 2.915 -18.544 C-0.533 -20.327 -1.764 -20.320 -5.119 -18.497" />
          </g>
        </g>
      </g>
    </svg>`;
  return preview;
}

function colorOscuro(hex, factor = 0.68) {
  return `#${[1, 3, 5]
    .map((inicio) => Math.round(parseInt(hex.slice(inicio, inicio + 2), 16) * factor)
      .toString(16).padStart(2, "0"))
    .join("")}`;
}

function colorRgb(hex) {
  return [1, 3, 5]
    .map((inicio) => parseInt(hex.slice(inicio, inicio + 2), 16))
    .join(" ");
}

function selectorColor(clave, etiqueta) {
  const label = nodo("label", "selector-color");
  label.append(nodo("span", null, etiqueta));
  const input = document.createElement("input");
  input.type = "color";
  input.id = clave;
  input.value = eleccion.apariencia[clave];
  input.addEventListener("input", () => {
    eleccion.apariencia[clave] = input.value.toUpperCase();
    sincronizarColores();
  });
  const codigo = nodo("code", null, input.value.toUpperCase());
  codigo.id = `${clave}-codigo`;
  label.append(input, codigo);
  return label;
}

function sincronizarColores() {
  const preview = document.getElementById("vibi-preview");
  if (preview) {
    preview.style.setProperty("--cara", eleccion.apariencia.color_cara);
    preview.style.setProperty("--antifaz", eleccion.apariencia.color_antifaz);
    preview.style.setProperty("--sombrero", eleccion.apariencia.color_sombrero);
    preview.style.setProperty(
      "--sombrero-sombra",
      colorOscuro(eleccion.apariencia.color_sombrero)
    );
    preview.style.setProperty(
      "--resplandor",
      colorRgb(eleccion.apariencia.color_sombrero)
    );
  }
  for (const clave of ["color_cara", "color_antifaz", "color_sombrero"]) {
    const input = document.getElementById(clave);
    if (input) input.value = eleccion.apariencia[clave];
    const codigo = document.getElementById(`${clave}-codigo`);
    if (codigo) codigo.textContent = eleccion.apariencia[clave];
  }
}

function pregunta(clave, etiqueta, marcador) {
  const label = nodo("label", "pregunta-installer");
  label.append(nodo("span", null, etiqueta));
  const textarea = document.createElement("textarea");
  textarea.id = `entrevista-${clave}`;
  textarea.rows = 2;
  textarea.maxLength = 200;
  textarea.placeholder = marcador;
  textarea.value = eleccion.entrevista[clave] || "";
  label.append(textarea);
  return label;
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

function revisarEntrevista() {
  seguir.disabled = !valor("entrevista-uso");
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
