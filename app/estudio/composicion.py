"""Las piezas generales: con ellas el agente compone lo que le pidan.

El engine no sabe qué es un sistema solar, un átomo de Bohr, un engranaje o
el atractor de Lorenz. Sabe tres cosas, y con ellas basta:

- **Objetos** (`estudio.objeto`): formas básicas anidables cuya posición,
  rotación, escala y tamaño son fórmulas. En una fórmula pueden aparecer los
  deslizadores, el tiempo `t` y las variables de los sistemas dinámicos, y se
  evalúan en cada fotograma: animar es escribir `[3*cos(t), 0, 3*sin(t)]`.
- **Sistemas dinámicos** (`estudio.sistema`): variables de estado y sus
  ecuaciones, escritas por el agente e integradas por el engine. Sus variables
  mueven los objetos.
- **Validación con números**: cada herramienta compila las fórmulas, las
  evalúa e integra, y le devuelve al agente lo que pasa de verdad (posiciones,
  rangos, periodos, si diverge) para que lo cuente sin inventar.

Todo lo compuesto así lleva procedencia «modelo»: la forma la ha decidido el
agente. Lo calculado (la integración, las evaluaciones) es del engine, y la
interfaz lo distingue de lo que viene de una fuente curada.
"""
from __future__ import annotations

import copy
import math
from typing import Literal

from pydantic import Field

from . import atlas, biblioteca, dinamica, escena as esc, generacion, sketchfab
from .expresiones import ExpresionInvalida, compilar, es_finito
from .primitivas import (
    EFECTOS,
    ERRORES_DEL_MODELO,
    PERMISOS,
    Numero,
    _Args,
    _fallo,
    _procedencia,
    _r,
)
from ..tools import Primitive

FORMAS = (
    "esfera", "caja", "cilindro", "cono", "toro", "plano",
    "tubo", "flecha", "texto", "grupo", "modelo",
)
# Qué significa `tamano` en cada forma, para el mensaje de error y la descripción.
TAMANOS = {
    "esfera": ["radio"],
    "caja": ["ancho", "alto", "fondo"],
    "cilindro": ["radio", "alto"],
    "cono": ["radio", "alto"],
    "toro": ["radio", "grosor"],
    "plano": ["ancho", "alto"],
    "tubo": ["radio"],
    "flecha": ["grosor"],
    "texto": ["altura"],
    "grupo": [],
    "modelo": ["largo"],
}
DEFECTOS = {
    "esfera": [0.5], "caja": [1, 1, 1], "cilindro": [0.5, 1], "cono": [0.5, 1],
    "toro": [1, 0.25], "plano": [2, 2], "tubo": [0.08], "flecha": [0.06],
    "texto": [0.4], "grupo": [], "modelo": [2],
}
MAX_PUNTOS = 400
MAX_ESTELA = 3000


# --- Sistemas dinámicos -----------------------------------------------------------


class SistemaArgs(_Args):
    id: str = Field(min_length=1, max_length=32)
    variables: dict[str, Numero] = Field(
        min_length=1, max_length=12,
        description="Variable de estado → valor inicial (número o fórmula con deslizadores)",
    )
    ecuaciones: dict[str, str] = Field(
        min_length=1, max_length=12,
        description="Variable → su derivada temporal, p. ej. {'theta': 'omega', "
        "'omega': '-g/L*sin(theta)'}. Puede usar las variables del sistema, "
        "deslizadores y t",
    )
    grafica: bool = Field(
        default=False, description="Dibuja la evolución temporal de las variables"
    )
    etiqueta: str | None = Field(default=None, max_length=80)


async def _sistema(user: dict, a: SistemaArgs) -> dict:
    try:
        async with esc.editar(user["id"]) as escena:
            if set(a.variables) != set(a.ecuaciones):
                raise esc.EscenaError(
                    "Cada variable necesita su ecuación y viceversa. Variables: "
                    f"{sorted(a.variables)}; ecuaciones: {sorted(a.ecuaciones)}"
                )
            elemento_id = esc.resolver_id(escena, "sistema", a.id)
            otras = {
                v for v, sistema_id in esc.variables_de_sistemas(escena).items()
                if sistema_id != elemento_id
            }
            parametros = esc.ids_de_parametros(escena)
            for variable in a.variables:
                if not esc.ID_VALIDO.match(variable) or variable == "t":
                    raise esc.EscenaError(f"Variable «{variable}» no válida (t está reservada)")
                if variable in parametros or variable in otras:
                    raise esc.EscenaError(
                        f"«{variable}» ya existe en la escena (deslizador o variable "
                        "de otro sistema): usa otro nombre"
                    )
            orden = tuple(a.variables)
            valores = esc.valores_parametros(escena)
            iniciales, fuentes_iniciales = {}, {}
            for variable, inicial in a.variables.items():
                expresion = compilar(str(inicial), parametros)
                fuentes_iniciales[variable] = expresion.fuente
                iniciales[variable] = expresion.evaluar(valores)
                if not es_finito(iniciales[variable]):
                    raise esc.EscenaError(f"El valor inicial de {variable} no es un número")
            permitidas = set(orden) | parametros | {"t"}
            derivadas = {v: compilar(a.ecuaciones[v], permitidas) for v in orden}
            usa = sorted(
                {n for e in derivadas.values() for n in e.variables} & parametros
            )
            resumen = dinamica.integrar(
                dinamica.Sistema(orden, iniciales, derivadas), valores
            )
            nuevo = {
                "id": elemento_id,
                "tipo": "sistema",
                "orden": list(orden),
                "iniciales": fuentes_iniciales,
                "ecuaciones": {v: derivadas[v].fuente for v in orden},
                "grafica": a.grafica,
                "usa": usa,
                "etiqueta": a.etiqueta or "Sistema dinámico",
                "color": esc.resolver_color(escena, None),
                "procedencia": _procedencia(
                    "modelo", "Ecuaciones escritas por el modelo; integradas por el engine (RK4)"
                ),
            }
            sustituido = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    return {
        "id": elemento_id,
        "sustituido": sustituido,
        "ecuaciones": {f"{v}'": derivadas[v].fuente for v in orden},
        "uso": f"Usa {', '.join(orden)} dentro de las fórmulas de estudio_objeto "
        "para que algo se mueva con el sistema",
        **resumen,
    }


# --- Objetos -----------------------------------------------------------------------


class GiroDeParteArg(_Args):
    partes: list[str] = Field(
        min_length=1, max_length=12,
        description="Partes del modelo; un * final es prefijo: ['wheel*']",
    )
    eje: Literal["x", "y", "z"] = Field(
        default="x", description="Eje propio de la parte (las ruedas de Kenney giran en x)"
    )
    angulo: Numero = Field(description="Grados; fórmula con t, deslizadores o variables")


class ArticulacionArg(_Args):
    partes: list[str] = Field(
        min_length=1, max_length=12,
        description="Partes del modelo que se mueven juntas; un * final es prefijo: ['door*']",
    )
    tipo: Literal["giro", "desliza"] = Field(
        default="giro", description="giro: bisagra o eje (grados); desliza: cajón o pistón (unidades de la escena)"
    )
    eje: Literal["x", "y", "z"] = Field(default="y", description="Eje propio de la parte")
    valor: Numero = Field(
        default=0, description="Grados o distancia; fórmula con t, deslizadores o variables"
    )
    minimo: float | None = Field(default=None, description="Tope: el valor nunca baja de aquí")
    maximo: float | None = Field(default=None, description="Tope: el valor nunca pasa de aquí")
    etiqueta: str | None = Field(default=None, max_length=60, description="Cómo la ve el alumno: 'Puerta'")


MAX_ARTICULACIONES = 8


class ObjetoArgs(_Args):
    id: str = Field(min_length=1, max_length=32)
    forma: Literal[
        "esfera", "caja", "cilindro", "cono", "toro", "plano",
        "tubo", "flecha", "texto", "grupo", "modelo",
    ]
    modelo: str | None = Field(
        default=None, max_length=124,
        description="forma modelo: id de estudio_biblioteca, p. ej. 'car-kit/sedan'",
    )
    girar_partes: list[GiroDeParteArg] = Field(
        default_factory=list, max_length=6,
        description="forma modelo: partes que giran sobre su eje (ruedas, hélices, palancas)",
    )
    articulaciones: list[ArticulacionArg] = Field(
        default_factory=list, max_length=MAX_ARTICULACIONES,
        description="forma modelo: puertas, tapas, cajones, palancas, brazos que se abren o "
        "deslizan, con topes. Con topes, el alumno también las mueve con el ratón",
    )
    colores_partes: dict[str, str] = Field(
        default_factory=dict, max_length=24,
        description="forma modelo: parte → color, p. ej. {'body': 'rojo'}; un * final es prefijo",
    )
    ocultar_partes: list[str] = Field(
        default_factory=list, max_length=24,
        description="forma modelo: partes que no se pintan (para enseñar el interior)",
    )
    padre: str | None = Field(
        default=None, description="Id de otro objeto: este se mueve, gira y escala con él"
    )
    posicion: list[Numero] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    rotacion: list[Numero] = Field(
        default_factory=lambda: [0, 0, 0], min_length=3, max_length=3,
        description="Grados en x, y, z",
    )
    escala: Numero | list[Numero] = 1
    tamano: list[Numero] | None = Field(
        default=None, max_length=3,
        description="esfera [radio]; caja [ancho, alto, fondo]; cilindro/cono "
        "[radio, alto]; toro [radio, grosor]; plano [ancho, alto]; tubo [radio]; "
        "flecha [grosor]; texto [altura]; modelo [largo] (su lado más largo; "
        "el resto, en proporción)",
    )
    puntos: list[list[Numero]] | None = Field(
        default=None, max_length=MAX_PUNTOS, description="Tubo: los puntos [x, y, z] que recorre"
    )
    direccion: list[Numero] | None = Field(
        default=None, min_length=3, max_length=3, description="Flecha: vector desde su posición"
    )
    texto: str | None = Field(default=None, max_length=160)
    color: str | None = None
    opacidad: float = Field(default=1.0, ge=0.05, le=1.0)
    brillo: float = Field(default=0.0, ge=0, le=3, description="Emisión: 0 mate, 1+ luminoso (estrellas, LEDs)")
    estela: int = Field(
        default=0, ge=0, le=MAX_ESTELA, description="Deja rastro de sus últimas N posiciones"
    )
    etiqueta: str | None = Field(default=None, max_length=80)


def _ancestros(escena: dict, padre: str | None) -> list[str]:
    cadena = []
    while padre:
        cadena.append(padre)
        elemento = esc.elemento(escena, padre)
        padre = elemento.get("padre") if elemento else None
        if len(cadena) > 64:
            break
    return cadena


MANUALES = ("posicion", "rotacion", "escala")


def _ajustes_conservados(anterior: dict | None, modelo: str) -> dict:
    """Lo que el alumno movió a mano en las partes sobrevive a que el modelo
    rehaga el objeto, mientras siga siendo el mismo modelo de la biblioteca.
    Colores y partes ocultas no: esos los vuelve a decidir la llamada nueva."""
    if not anterior or anterior.get("modelo") != modelo:
        return {}
    conservados = {}
    for parte, ajuste in (anterior.get("ajustes") or {}).items():
        manual = {k: v for k, v in ajuste.items() if k in MANUALES}
        if manual:
            conservados[parte] = manual
    return conservados


async def _objeto(user: dict, a: ObjetoArgs) -> dict:
    ficha = None
    if a.forma == "modelo":
        if not a.modelo:
            raise _fallo(esc.EscenaError("Para forma modelo hace falta modelo: un id de estudio_biblioteca"))
        if biblioteca.ficha(a.modelo) is None and not a.modelo.startswith("sketchfab/"):
            raise _fallo(esc.EscenaError(
                f"«{a.modelo}» no está en la biblioteca. Busca el id con "
                "estudio_biblioteca (p. ej. consulta 'car', 'rocket', 'cannon')"
            ))
        try:
            # Fuera del candado: la primera vez descarga el kit entero, o
            # importa el modelo de Sketchfab.
            ficha = await biblioteca.preparar(a.modelo)
        except biblioteca.BibliotecaError as error:
            raise _fallo(error) from error
    elif a.modelo or a.girar_partes or a.articulaciones or a.colores_partes or a.ocultar_partes:
        raise _fallo(esc.EscenaError(
            "modelo, girar_partes, articulaciones, colores_partes y ocultar_partes son "
            "solo para forma modelo"
        ))
    try:
        async with esc.editar(user["id"]) as escena:
            elemento_id = esc.resolver_id(escena, "objeto", a.id)
            if a.padre is not None:
                padre = esc.elemento(escena, a.padre)
                if padre is None or padre["tipo"] != "objeto":
                    raise esc.EscenaError(f"El padre «{a.padre}» no es un objeto de la escena")
                if elemento_id in _ancestros(escena, a.padre):
                    raise esc.EscenaError("Eso crearía un ciclo de padres")
            permitidas = esc.nombres_vivos(escena)
            sistemas = set(esc.variables_de_sistemas(escena))
            valores = {**esc.valores_parametros(escena), "t": 0.0}
            for sistema in (e for e in escena["elementos"] if e["tipo"] == "sistema"):
                for variable, inicial in sistema["iniciales"].items():
                    valores[variable] = compilar(inicial, esc.ids_de_parametros(escena)).evaluar(valores)
            usadas: set[str] = set()

            def vector(lista: list[Numero], nombre: str) -> tuple[list[str], list[float | None]]:
                fuentes, ahora = [], []
                for componente in lista:
                    expresion = compilar(str(componente), permitidas)
                    usadas.update(expresion.variables)
                    fuentes.append(expresion.fuente)
                    ahora.append(_r(expresion.evaluar(valores)))
                if any(v is None for v in ahora):
                    raise esc.EscenaError(f"{nombre} no da un número en t = 0: {ahora}")
                return fuentes, ahora

            posicion, posicion_ahora = vector(a.posicion, "posicion")
            rotacion, _ = vector(a.rotacion, "rotacion")
            escala_lista = a.escala if isinstance(a.escala, list) else [a.escala] * 3
            if len(escala_lista) != 3:
                raise esc.EscenaError("escala es un número o [x, y, z]")
            escala, _ = vector(escala_lista, "escala")
            nombres_tamano = TAMANOS[a.forma]
            tamano_lista = a.tamano if a.tamano is not None else DEFECTOS[a.forma]
            if len(tamano_lista) != len(nombres_tamano):
                raise esc.EscenaError(
                    f"Para {a.forma}, tamano es [{', '.join(nombres_tamano)}]"
                    if nombres_tamano else "Un grupo no tiene tamaño"
                )
            tamano, tamano_ahora = vector(tamano_lista, "tamano")
            if any(t is not None and t <= 0 for t in tamano_ahora):
                raise esc.EscenaError("Los tamaños tienen que ser positivos")
            nuevo: dict = {
                "id": elemento_id,
                "tipo": "objeto",
                "forma": a.forma,
                "padre": a.padre,
                "posicion": posicion,
                "rotacion": rotacion,
                "escala": escala,
                "tamano": tamano,
                "opacidad": a.opacidad,
                "brillo": a.brillo,
                "estela": a.estela,
                "color": esc.resolver_color(escena, a.color),
                "etiqueta": a.etiqueta or a.texto or "",
            }
            if a.forma == "tubo":
                if not a.puntos or len(a.puntos) < 2:
                    raise esc.EscenaError("Un tubo necesita al menos dos puntos")
                nuevo["puntos"] = [vector(p, "puntos")[0] for p in a.puntos if len(p) == 3]
                if len(nuevo["puntos"]) != len(a.puntos):
                    raise esc.EscenaError("Cada punto del tubo es [x, y, z]")
            if a.forma == "flecha":
                direccion, direccion_ahora = vector(a.direccion or [1, 0, 0], "direccion")
                if math.hypot(*direccion_ahora) == 0:
                    raise esc.EscenaError("La flecha tiene dirección nula en t = 0")
                nuevo["direccion"] = direccion
            if a.forma == "texto":
                if not a.texto:
                    raise esc.EscenaError("Un texto necesita texto")
                nuevo["texto"] = a.texto
            medidas_en_escena = None
            if ficha is not None:
                ajustes = _ajustes_conservados(esc.elemento(escena, elemento_id), ficha["id"])

                def partes_de(patrones: list[str], para: str) -> list[str]:
                    partes, sueltas = biblioteca.expandir_partes(ficha, patrones)
                    if sueltas:
                        raise esc.EscenaError(
                            f"{para}: {ficha['id']} no tiene las partes {sueltas}. Tiene: "
                            f"{', '.join(ficha['partes']) or 'ninguna (es una sola pieza)'}"
                        )
                    return partes

                # girar_partes es una articulación de giro sin topes (ruedas).
                pedidas = [
                    ArticulacionArg(partes=g.partes, tipo="giro", eje=g.eje, valor=g.angulo)
                    for g in a.girar_partes
                ] + list(a.articulaciones)
                escala_modelo = (tamano_ahora[0] or 1) / max(max(ficha["medidas"]), 1e-6)
                if not pedidas:
                    # Lo que viene articulado de serie (un URDF) se puede abrir
                    # con el ratón sin que el agente tenga que pedirlo. Los topes
                    # al deslizar están en unidades del archivo: a la escena.
                    for sugerida in ficha.get("articulaciones_sugeridas", []):
                        datos = dict(sugerida)
                        if datos["tipo"] == "desliza":
                            for clave in ("minimo", "maximo"):
                                if clave in datos:
                                    datos[clave] = _r(datos[clave] * escala_modelo)
                        pedidas.append(ArticulacionArg(**datos))
                if len(pedidas) > MAX_ARTICULACIONES:
                    raise esc.EscenaError(
                        f"Como mucho {MAX_ARTICULACIONES} articulaciones (girar_partes incluidas)"
                    )
                articulaciones = []
                for pedida in pedidas:
                    if (
                        pedida.minimo is not None
                        and pedida.maximo is not None
                        and pedida.minimo >= pedida.maximo
                    ):
                        raise esc.EscenaError("En una articulación, minimo tiene que ser menor que maximo")
                    valor, _ = vector([pedida.valor], "valor de la articulación")
                    articulacion = {
                        "partes": partes_de(pedida.partes, "articulaciones"),
                        "tipo": pedida.tipo,
                        "eje": pedida.eje,
                        "valor": valor[0],
                    }
                    for clave in ("minimo", "maximo", "etiqueta"):
                        if getattr(pedida, clave) is not None:
                            articulacion[clave] = getattr(pedida, clave)
                    articulaciones.append(articulacion)

                for patron, color in a.colores_partes.items():
                    for parte in partes_de([patron], "colores_partes"):
                        ajustes.setdefault(parte, {})["color"] = esc.resolver_color(escena, color)
                for parte in partes_de(a.ocultar_partes, "ocultar_partes"):
                    ajustes.setdefault(parte, {})["oculta"] = True
                medidas_en_escena = [_r(m * escala_modelo) for m in ficha["medidas"]]
                nuevo.update(
                    {
                        "modelo": ficha["id"],
                        "url": f"/api/estudio/biblioteca/{ficha['id']}",
                        # Las partes se señalan por su nombre, como en los
                        # modelos del catálogo: «coche.wheel-front-left».
                        "partes": {p: p for p in ficha["partes"]},
                        "articulaciones": articulaciones,
                        "ajustes": ajustes,
                    }
                )
                if any(k in MANUALES for ajuste in ajustes.values() for k in ajuste):
                    nuevo["manual"] = True
            nuevo["usa"] = sorted(usadas - {"t"})
            nuevo["anima"] = bool(usadas & ({"t"} | sistemas))
            cita, enlace = biblioteca.fuente(ficha) if ficha is not None else ("", None)
            nuevo["procedencia"] = (
                # Generado por IA: una forma creíble, no verificada. Va como lo
                # redactado por Vibi, no como catálogo.
                _procedencia(
                    "modelo",
                    f"Generado por IA ({ficha['autor']}) a partir de «{ficha['titulo']}»: "
                    "forma aproximada, no un modelo verificado; colocado por el modelo",
                )
                if ficha is not None and ficha.get("generado")
                else _procedencia(
                    "catalogo",
                    f"{cita}; colocado y animado por el modelo",
                    **({"url": enlace} if enlace else {}),
                )
                if ficha is not None
                else _procedencia(
                    "modelo",
                    "Composición del modelo; fórmulas evaluadas por el engine en cada fotograma",
                )
            )
            avisos = []
            mitades = [d / 2 for d in escena.get("espacio", [10, 6, 6])]
            if a.padre is None and any(
                abs(p) > m for p, m in zip(posicion_ahora, mitades) if p is not None
            ):
                avisos.append(
                    f"En t = 0 está en {posicion_ahora}, fuera del espacio "
                    f"{escena.get('espacio')} (centrado en el origen): la cámara no "
                    "lo encuadrará. Ajusta posiciones o el espacio de estudio_nueva_escena"
                )
            sustituido = esc.poner(escena, nuevo)
    except ERRORES_DEL_MODELO as error:
        raise _fallo(error) from error
    respuesta = {
        "id": elemento_id,
        "sustituido": sustituido,
        "posicion_en_t0": posicion_ahora,
        "se_mueve": nuevo["anima"],
        "depende_de": nuevo["usa"],
        "avisos": avisos,
    }
    if medidas_en_escena is not None:
        ancho, alto, largo = medidas_en_escena
        respuesta["medidas_en_escena"] = {"ancho_x": ancho, "alto_y": alto, "largo_z": largo}
        respuesta["colocacion"] = (
            "posicion es el centro de su base: apoyado en y = s, su parte de "
            f"arriba queda en y = s + {alto}. Sin rotar, su frente mira a +z (hacia "
            "la cámara en 2D); rotacion [0, 90, 0] lo pone mirando a +x"
        )
        if ficha["partes"]:
            respuesta["partes"] = ficha["partes"]
        pistas = biblioteca.articulables(ficha)
        if pistas:
            respuesta["articulables"] = pistas
        if nuevo.get("articulaciones"):
            respuesta["articulaciones"] = [
                {k: v for k, v in art.items() if k != "partes"} | {"partes": len(art["partes"])}
                for art in nuevo["articulaciones"]
            ]
        if ficha.get("autor"):
            respuesta["colocacion"] = (
                "posicion es el centro de su base y su alto en la escena es "
                f"{alto}. Es de {ficha.get('plataforma', 'Sketchfab')}: su frente puede "
                "no mirar a +z. Haz una estudio_captura para ver cómo queda y gíralo si hace falta"
            )
            respuesta["cita"] = biblioteca.fuente(ficha)[0]
    return respuesta


# --- Generar con IA lo que no está en ninguna biblioteca ------------------------


class GenerarModeloArgs(_Args):
    descripcion: str = Field(
        min_length=3, max_length=400,
        description="En inglés y concreta: el objeto, su estilo y sus materiales, p. ej. "
        "'a four-stroke engine cutaway, metal, educational model'. Sin escena ni fondo",
    )
    id: str = Field(min_length=1, max_length=32)
    padre: str | None = None
    posicion: list[Numero] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    rotacion: list[Numero] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    tamano: Numero = Field(default=2, description="Su lado más largo, en unidades de la escena")
    etiqueta: str | None = Field(default=None, max_length=80)


async def _generar_modelo(user: dict, a: GenerarModeloArgs) -> dict:
    try:
        ficha = await generacion.obtener(user["id"], a.descripcion)
    except generacion.GeneracionPendiente:
        return {
            "estado": "generando",
            "nota": "Aún se está generando (tarda de 30 s a 2 min). Sigue con el resto de "
            "la escena y vuelve a llamar a estudio_generar_modelo con la misma "
            "descripcion: lo recoge sin generarlo otra vez",
        }
    except biblioteca.BibliotecaError as error:
        raise _fallo(error) from error
    respuesta = await _objeto(user, ObjetoArgs(
        id=a.id, forma="modelo", modelo=ficha["id"], padre=a.padre, posicion=a.posicion,
        rotacion=a.rotacion, tamano=[a.tamano], etiqueta=a.etiqueta,
    ))
    respuesta["estado"] = "listo"
    respuesta["aviso_generado"] = (
        "Es una forma generada por IA: díselo al alumno y no cuentes sus detalles "
        "como si fueran exactos. Mira cómo ha quedado con estudio_captura"
    )
    return respuesta


# --- Retocar un objeto que ya está ------------------------------------------------


class EditarObjetoArgs(_Args):
    id: str = Field(min_length=1, max_length=32, description="Un objeto que ya está en la escena")
    posicion: list[Numero] | None = Field(default=None, min_length=3, max_length=3)
    rotacion: list[Numero] | None = Field(default=None, min_length=3, max_length=3)
    escala: Numero | list[Numero] | None = None
    tamano: list[Numero] | None = Field(default=None, max_length=3)
    color: str | None = None
    opacidad: float | None = Field(default=None, ge=0.05, le=1.0)
    brillo: float | None = Field(default=None, ge=0, le=3)
    estela: int | None = Field(default=None, ge=0, le=MAX_ESTELA)
    etiqueta: str | None = Field(default=None, max_length=80)
    padre: str | None = None
    girar_partes: list[GiroDeParteArg] | None = Field(default=None, max_length=6)
    articulaciones: list[ArticulacionArg] | None = Field(default=None, max_length=MAX_ARTICULACIONES)
    colores_partes: dict[str, str] | None = Field(default=None, max_length=24)
    ocultar_partes: list[str] | None = Field(default=None, max_length=24)


def _como_argumentos(e: dict) -> dict:
    """Un objeto guardado, de vuelta en la forma de estudio_objeto."""
    argumentos = {
        "id": e["id"],
        "forma": e["forma"],
        "padre": e.get("padre"),
        "posicion": e["posicion"],
        "rotacion": e["rotacion"],
        "escala": e["escala"],
        "tamano": e["tamano"] if e["forma"] != "grupo" else None,
        "color": e["color"],
        "opacidad": e["opacidad"],
        "brillo": e["brillo"],
        "estela": e["estela"],
        "etiqueta": e.get("etiqueta") or None,
    }
    for clave in ("puntos", "direccion", "texto", "modelo"):
        if e.get(clave) is not None:
            argumentos[clave] = e[clave]
    if e.get("giros"):  # escenas de antes de las articulaciones
        argumentos["girar_partes"] = e["giros"]
    if e.get("articulaciones"):
        argumentos["articulaciones"] = e["articulaciones"]
    ajustes = e.get("ajustes") or {}
    colores = {p: a["color"] for p, a in ajustes.items() if a.get("color")}
    if colores:
        argumentos["colores_partes"] = colores
    ocultas = [p for p, a in ajustes.items() if a.get("oculta")]
    if ocultas:
        argumentos["ocultar_partes"] = ocultas
    return argumentos


async def _editar_objeto(user: dict, a: EditarObjetoArgs) -> dict:
    existente = esc.elemento(esc.cargar(user["id"]), a.id)
    if existente is None or existente["tipo"] != "objeto":
        raise _fallo(esc.EscenaError(
            f"«{a.id}» no es un objeto de la escena: créalo con estudio_objeto"
        ))
    argumentos = _como_argumentos(existente)
    argumentos.update(a.model_dump(exclude_unset=True, exclude={"id"}))
    try:
        completos = ObjetoArgs.model_validate(argumentos)
    except ValueError as error:
        raise _fallo(error) from error
    return await _objeto(user, completos)


def _constante(fuente: str) -> bool:
    try:
        return not compilar(fuente, set()).variables
    except ExpresionInvalida:
        return False


def _numeros(valores: list[float], nombre: str) -> list[str]:
    if len(valores) != 3 or not all(math.isfinite(v) and abs(v) < 1e4 for v in valores):
        raise esc.EscenaError(f"{nombre} tiene que ser [x, y, z] con números razonables")
    return [f"{v:.4g}" if abs(v) >= 1e-4 else "0" for v in valores]


async def ajustar_a_mano(
    user_id: str,
    objeto_id: str,
    *,
    parte: str | None = None,
    posicion: list[float] | None = None,
    rotacion: list[float] | None = None,
    escala: list[float] | None = None,
    restablecer: bool = False,
) -> dict:
    """Lo que el alumno mueve, gira o escala con el ratón, guardado en la escena.

    Un objeto entero solo se mueve a mano si su colocación es fija: si depende
    de t, de un deslizador o de un sistema, el gizmo la pisaría y la animación
    se perdería. La primera vez se guarda la colocación original para poder
    restablecerla. Una parte de un modelo guarda su posición, giro y escala
    locales, en las unidades del archivo original.
    """
    async with esc.editar(user_id) as escena:
        e = esc.elemento(escena, objeto_id)
        if e is None or e["tipo"] != "objeto":
            raise esc.EscenaError(f"«{objeto_id}» no es un objeto de la escena")
        if parte is not None:
            if parte not in (e.get("partes") or {}):
                raise esc.EscenaError(f"«{objeto_id}» no tiene la parte «{parte}»")
            ajustes = e.setdefault("ajustes", {})
            ajuste = ajustes.setdefault(parte, {})
            if restablecer:
                for clave in MANUALES:
                    ajuste.pop(clave, None)
            else:
                for clave, valor in (("posicion", posicion), ("rotacion", rotacion), ("escala", escala)):
                    if valor is not None:
                        ajuste[clave] = [float(v) for v in _numeros(valor, clave)]
            if not ajuste:
                ajustes.pop(parte)
        elif restablecer:
            original = e.pop("original", None)
            if original:
                e.update(original)
        else:
            movidas = {
                clave: valor
                for clave, valor in (("posicion", posicion), ("rotacion", rotacion), ("escala", escala))
                if valor is not None
            }
            fijas = [c for c in movidas if all(_constante(f) for f in e[c])]
            if len(fijas) != len(movidas):
                raise esc.EscenaError(
                    f"«{e.get('etiqueta') or objeto_id}» se mueve con fórmulas "
                    "(tiempo, deslizadores o un sistema): no se puede colocar a mano"
                )
            e.setdefault("original", {c: list(e[c]) for c in MANUALES})
            for clave, valor in movidas.items():
                e[clave] = _numeros(valor, clave)
        e["manual"] = bool(e.get("original") or any(
            any(k in MANUALES for k in a) for a in (e.get("ajustes") or {}).values()
        ))
        return copy.deepcopy(e)


# --- Biblioteca de objetos ----------------------------------------------------------


class BibliotecaArgs(_Args):
    consulta: str = Field(
        default="", max_length=80,
        description="Palabras en inglés: 'car', 'wheel', 'rocket', 'cannon', 'tree', "
        "'chair', 'microscope'. Vacía = qué kits hay",
    )
    sketchfab: bool = Field(
        default=True,
        description="Buscar también en Sketchfab (modelos realistas CC0/CC BY): "
        "para lo que Kenney no tiene o cuando hace falta realismo",
    )


async def _biblioteca(user: dict, a: BibliotecaArgs) -> dict:
    if not a.consulta.strip():
        return {"kits": biblioteca.kits(), "nota": "Busca con una consulta en inglés"}
    try:
        resultado = biblioteca.buscar(a.consulta)
    except biblioteca.BibliotecaError as error:
        raise _fallo(error) from error
    if a.sketchfab and sketchfab.disponible():
        try:
            resultado["sketchfab"] = await sketchfab.buscar(a.consulta)
        except biblioteca.BibliotecaError as error:
            resultado["sketchfab_aviso"] = str(error)
        if resultado.get("sketchfab"):
            resultado["nota_sketchfab"] = (
                "Modelos de Sketchfab, realistas: se usan igual (modelo = su id) y "
                "la primera vez se descargan (unos segundos). Sus medidas y partes "
                "llegan en la respuesta de estudio_objeto. Prefiere los de pocas caras"
            )
    resultado["nota"] = (
        "Ponlo con estudio_objeto forma 'modelo' y modelo = id. medidas son las "
        "del modelo original (frente hacia +z); en la escena se escala para que "
        "su lado más largo mida tamano[0]. Las partes con nombre se pueden "
        "girar (girar_partes), articular con topes (articulaciones: puertas, "
        "tapas, cajones; articulables dice el eje) y señalar en los pasos "
        "(resaltar: ['id.parte'])"
    )
    if not resultado["modelos"] and not resultado.get("sketchfab"):
        resultado["nota"] = (
            "Nada con ese nombre. Prueba otra palabra en inglés o estudio_biblioteca "
            "sin consulta para ver los kits; si no existe, "
            + ("genéralo con estudio_generar_modelo o compón con formas"
               if generacion.disponible() else "compón con formas")
        )
    return resultado


# --- Atlas anatómico ------------------------------------------------------------


class AtlasBuscarArgs(_Args):
    consulta: str = Field(
        min_length=2, max_length=80,
        description="En inglés, como en los atlas: 'kidney', 'femur', 'brachial plexus', 'heart'",
    )


async def _atlas_buscar(user: dict, a: AtlasBuscarArgs) -> dict:
    try:
        resultado = atlas.buscar(a.consulta)
    except atlas.AtlasError as error:
        raise _fallo(error) from error
    resultado["nota"] = (
        "Pasa a estudio_atlas nombres de pieza o de grupo tal cual aparecen aquí "
        "(un grupo carga todas sus piezas). .l y .r son izquierda y derecha."
    )
    if not atlas.disponible():
        resultado["aviso"] = "El atlas no está instalado en este servidor: se puede buscar pero no cargar"
    return resultado


class AtlasArgs(_Args):
    estructuras: list[str] = Field(
        min_length=1, max_length=80,
        description="Nombres exactos de pieza o de grupo devueltos por estudio_atlas_buscar",
    )
    nombres: dict[str, str] = Field(
        default_factory=dict,
        description="Pieza → nombre para el alumno (p. ej. {'Kidney.l': 'Riñón izquierdo'}); "
        "varias piezas pueden compartir nombre y se señalan juntas",
    )
    resaltar: list[str] = Field(default_factory=list, max_length=40)
    id: str | None = None
    etiqueta: str | None = Field(default=None, max_length=80)


async def _atlas(user: dict, a: AtlasArgs) -> dict:
    try:
        piezas, desconocidas = atlas.expandir(a.estructuras)
        if desconocidas:
            sugerencias = {d: atlas.buscar(d.split(".")[0], 5)["piezas"] for d in desconocidas}
            raise atlas.AtlasError(
                f"No están en el atlas: {desconocidas}. Búscalas con estudio_atlas_buscar; "
                f"parecidas: { {d: [p['nombre'] for p in v] for d, v in sugerencias.items()} }"
            )
        if len(piezas) > atlas.MAX_PIEZAS:
            raise atlas.AtlasError(
                f"Son {len(piezas)} piezas; el máximo es {atlas.MAX_PIEZAS}. Elige grupos más pequeños"
            )
        vertices = atlas.presupuesto(piezas)
        if vertices > atlas.MAX_VERTICES:
            raise atlas.AtlasError(f"Demasiada geometría ({vertices} vértices): elige menos piezas")
        sobrantes = set(a.nombres) - set(piezas)
        if sobrantes:
            raise atlas.AtlasError(f"nombres incluye piezas que no se cargan: {sorted(sobrantes)}")
        clave = await atlas.exportar(piezas)
        partes = {p: a.nombres.get(p, p) for p in piezas}
        modelo = {"partes": partes}
        from .modelos import normalizar_partes

        resaltadas, no_existen = normalizar_partes(modelo, a.resaltar)
        async with esc.editar(user["id"]) as escena:
            elemento_id = esc.resolver_id(escena, "atlas", a.id)
            nuevo = {
                "id": elemento_id,
                "tipo": "modelo",
                "modelo_id": f"atlas-{clave}",
                "url": f"/api/estudio/atlas/{clave}/archivo",
                "partes": partes,
                "resaltadas": resaltadas,
                "usa": [],
                "etiqueta": a.etiqueta or ", ".join(dict.fromkeys(partes.values()))[:80],
                "color": esc.resolver_color(escena, None),
                "procedencia": _procedencia(
                    "catalogo", f"{atlas.indice()['fuente']}; {len(piezas)} piezas"
                ),
            }
            sustituido = esc.poner(escena, nuevo)
    except (atlas.AtlasError, *ERRORES_DEL_MODELO) as error:
        raise _fallo(error) from error
    return {
        "id": elemento_id,
        "sustituido": sustituido,
        "piezas": len(piezas),
        "vertices": vertices,
        "nombres_para_senalar": list(dict.fromkeys(partes.values())),
        "resaltadas": sorted({partes[p] for p in resaltadas}),
        "no_existen": no_existen,
    }


INTRO_COMPOSICION = (
    "Pieza general de Estudio: con estudio_objeto y estudio_sistema se compone "
    "cualquier visualización que no tenga atajo. "
)

PRIMITIVAS: dict[str, Primitive] = {
    "estudio.atlas_buscar": Primitive(
        "estudio.atlas_buscar", "Estudio: buscar en el atlas anatómico",
        "Busca en el atlas anatómico Z-Anatomy (~3.900 piezas: huesos, "
        "músculos, órganos, vasos, nervios, cerebro…) por palabras en inglés. "
        "Devuelve piezas y grupos (p. ej. 'Heart', 'Urinary system', 'Bones of "
        "hand'). Úsala siempre que haya que enseñar anatomía, antes de "
        "estudio_atlas.",
        ("estudio:read:self",), (), AtlasBuscarArgs, _atlas_buscar,
    ),
    "estudio.atlas": Primitive(
        "estudio.atlas", "Estudio: cargar anatomía",
        "Carga en Estudio piezas o grupos del atlas anatómico con su geometría "
        "real (BodyParts3D), coloreadas por sistema. Con nombres les das el "
        "nombre que verá el alumno; después se señalan en los pasos con "
        "resaltar: ['atlas1.Riñón izquierdo']. La primera vez tarda unos "
        "segundos (se extrae con Blender); después va de caché.",
        PERMISOS, EFECTOS, AtlasArgs, _atlas,
    ),
    "estudio.biblioteca": Primitive(
        "estudio.biblioteca", "Estudio: buscar objetos 3D",
        "Busca en la biblioteca de objetos 3D (≈1.400 modelos CC0 de Kenney: "
        "vehículos con ruedas que giran, cohetes, barcos, cañones, trenes, "
        "herramientas, muebles, comida, árboles, rocas, rampas, palancas, muelles…) "
        "y, si el servidor tiene token, en Sketchfab: modelos realistas CC0/CC BY "
        "de casi cualquier cosa (microscopios, órganos, volcanes, instrumentos, "
        "edificios). Úsala ANTES de componer con formas cualquier objeto del mundo "
        "real: un coche, un cohete o una mesa hechos con cajas quedan mal. Kenney "
        "es estilo juguete y tiene partes que giran; Sketchfab, realismo. Devuelve "
        "ids, medidas y partes para estudio_objeto con forma 'modelo'.",
        ("estudio:read:self",), (), BibliotecaArgs, _biblioteca,
    ),
    "estudio.objeto": Primitive(
        "estudio.objeto", "Estudio: objeto",
        INTRO_COMPOSICION
        + "Crea o sustituye un objeto 3D en el espacio libre de la escena "
        "(centrado en el origen, y hacia arriba). Formas: esfera, caja, "
        "cilindro, cono, toro, plano, tubo (por puntos), flecha, texto, grupo "
        "(vacío, para anidar) y modelo (un objeto real de estudio_biblioteca: "
        "úsalo para coches, cohetes, barcos, herramientas, muebles… en vez de "
        "montarlos con cajas; posicion es el centro de su base, girar_partes "
        "hace rodar sus ruedas y articulaciones abre puertas, tapas y cajones "
        "con topes que el alumno puede mover). Los cilindros y conos van en vertical (eje y): "
        "una rueda hecha con cilindro necesita rotacion [90, 0, 0]. posicion, rotacion (grados), escala, tamano, "
        "puntos y direccion admiten fórmulas con deslizadores, t (segundos) y "
        "variables de sistemas: [3*cos(t), 0, 3*sin(t)] gira; con padre se "
        "anida (una luna dentro de un planeta). estela deja rastro. Devuelve "
        "dónde queda en t = 0 y avisa si se sale del espacio.",
        PERMISOS, EFECTOS, ObjetoArgs, _objeto,
    ),
    "estudio.editar_objeto": Primitive(
        "estudio.editar_objeto", "Estudio: retocar un objeto",
        "Cambia solo lo que pases de un objeto que ya está (posición, giro, "
        "escala, tamaño, color, opacidad, etiqueta, padre, partes que giran, "
        "colores u ocultación de partes) y conserva el resto. Úsala para "
        "corregir tras estudio_validar o estudio_captura en vez de rehacer el "
        "objeto. Lo que el alumno haya movido a mano (ver_escena lo marca como "
        "manual) es su posición actual: respétala salvo que te pida moverlo.",
        PERMISOS, EFECTOS, EditarObjetoArgs, _editar_objeto,
    ),
    "estudio.sistema": Primitive(
        "estudio.sistema", "Estudio: sistema dinámico",
        INTRO_COMPOSICION
        + "Declara un sistema de ecuaciones diferenciales (variables de estado, "
        "valores iniciales y derivadas) que el engine integra en vivo con RK4: "
        "péndulos, órbitas, poblaciones, circuitos, epidemias, Lorenz… Sus "
        "variables se pueden usar en las fórmulas de estudio_objeto para mover "
        "cosas, y con grafica=true se dibuja su evolución. Devuelve rangos, "
        "periodo y si diverge, calculados en 30 s simulados.",
        PERMISOS, EFECTOS, SistemaArgs, _sistema,
    ),
}

# Generar cuesta dinero: sin clave, la herramienta ni se le enseña al agente.
if generacion.disponible():
    PRIMITIVAS["estudio.generar_modelo"] = Primitive(
        "estudio.generar_modelo", "Estudio: generar un objeto 3D con IA",
        "Último recurso para objetos que NO están en estudio_biblioteca (ni Kenney "
        "ni Sketchfab): genera un modelo 3D a partir de una descripción en inglés "
        "(Hunyuan3D) y lo pone en la escena como estudio_objeto con forma modelo. "
        "Sale una forma creíble pero no exacta, sin partes con nombre; cuesta dinero "
        "y tarda de 30 s a 2 min (si no llega, devuelve estado 'generando': vuelve "
        "a llamarla con la misma descripción). La misma descripción no se genera dos veces.",
        PERMISOS, EFECTOS, GenerarModeloArgs, _generar_modelo,
    )
