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

import math
from typing import Literal

from pydantic import Field

from . import atlas, dinamica, escena as esc
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
    "tubo", "flecha", "texto", "grupo",
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
}
DEFECTOS = {
    "esfera": [0.5], "caja": [1, 1, 1], "cilindro": [0.5, 1], "cono": [0.5, 1],
    "toro": [1, 0.25], "plano": [2, 2], "tubo": [0.08], "flecha": [0.06],
    "texto": [0.4], "grupo": [],
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


class ObjetoArgs(_Args):
    id: str = Field(min_length=1, max_length=32)
    forma: Literal[
        "esfera", "caja", "cilindro", "cono", "toro", "plano",
        "tubo", "flecha", "texto", "grupo",
    ]
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
        "flecha [grosor]; texto [altura]",
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


async def _objeto(user: dict, a: ObjetoArgs) -> dict:
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
            nuevo["usa"] = sorted(usadas - {"t"})
            nuevo["anima"] = bool(usadas & ({"t"} | sistemas))
            nuevo["procedencia"] = _procedencia(
                "modelo",
                "Composición del modelo; fórmulas evaluadas por el engine en cada fotograma",
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
    return {
        "id": elemento_id,
        "sustituido": sustituido,
        "posicion_en_t0": posicion_ahora,
        "se_mueve": nuevo["anima"],
        "depende_de": nuevo["usa"],
        "avisos": avisos,
    }


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
    "estudio.objeto": Primitive(
        "estudio.objeto", "Estudio: objeto",
        INTRO_COMPOSICION
        + "Crea o sustituye un objeto 3D en el espacio libre de la escena "
        "(centrado en el origen, y hacia arriba). Formas: esfera, caja, "
        "cilindro, cono, toro, plano, tubo (por puntos), flecha, texto y grupo "
        "(vacío, para anidar). posicion, rotacion (grados), escala, tamano, "
        "puntos y direccion admiten fórmulas con deslizadores, t (segundos) y "
        "variables de sistemas: [3*cos(t), 0, 3*sin(t)] gira; con padre se "
        "anida (una luna dentro de un planeta). estela deja rastro. Devuelve "
        "dónde queda en t = 0 y avisa si se sale del espacio.",
        PERMISOS, EFECTOS, ObjetoArgs, _objeto,
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
