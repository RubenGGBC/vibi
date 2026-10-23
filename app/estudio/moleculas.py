"""Moléculas con su geometría real, sacada de PubChem.

Una molécula no se dibuja «de memoria»: se le pide a PubChem su conformación
3D (el SDF que publica para cada compuesto) y se pinta lo que hay en ese
archivo, átomo por átomo y enlace por enlace. La escena guarda el CID, así que
cualquiera puede comprobar de dónde salió.

Si PubChem no responde, quedan unas pocas moléculas de libro con la geometría
calculada aquí a partir de longitudes y ángulos de enlace conocidos.
"""
from __future__ import annotations

import math
from urllib.parse import quote

import httpx

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
MAX_ATOMOS = 300
TIMEOUT = 12.0


class MoleculaNoEncontrada(LookupError):
    pass


def parsear_sdf(texto: str) -> tuple[list[dict], list[dict]]:
    """Átomos y enlaces de un molfile V2000 (el primer registro del SDF)."""
    lineas = texto.splitlines()
    if len(lineas) < 4:
        raise ValueError("SDF incompleto")
    cuenta = lineas[3]
    if "V3000" in cuenta:
        raise ValueError("Formato V3000 no soportado")
    n_atomos = int(cuenta[0:3])
    n_enlaces = int(cuenta[3:6])
    if n_atomos > MAX_ATOMOS:
        raise ValueError(f"La molécula tiene {n_atomos} átomos; el máximo es {MAX_ATOMOS}")
    atomos = []
    for linea in lineas[4 : 4 + n_atomos]:
        atomos.append(
            {
                "elemento": linea[31:34].strip(),
                "posicion": [
                    float(linea[0:10]),
                    float(linea[10:20]),
                    float(linea[20:30]),
                ],
            }
        )
    enlaces = []
    for linea in lineas[4 + n_atomos : 4 + n_atomos + n_enlaces]:
        enlaces.append(
            {
                "a": int(linea[0:3]) - 1,
                "b": int(linea[3:6]) - 1,
                "orden": int(linea[6:9]),
            }
        )
    return atomos, enlaces


def formula_de(atomos: list[dict]) -> str:
    """Fórmula de Hill: C primero, H después, el resto por orden alfabético."""
    cuenta: dict[str, int] = {}
    for atomo in atomos:
        cuenta[atomo["elemento"]] = cuenta.get(atomo["elemento"], 0) + 1
    orden = (
        ["C", "H"] + sorted(e for e in cuenta if e not in {"C", "H"})
        if "C" in cuenta
        else sorted(cuenta)
    )
    return "".join(
        f"{e}{cuenta[e] if cuenta[e] > 1 else ''}" for e in orden if e in cuenta
    )


async def desde_pubchem(consulta: str) -> dict:
    """Busca por nombre (en inglés) o por CID y trae la conformación 3D."""
    consulta = consulta.strip()
    async with httpx.AsyncClient(timeout=TIMEOUT) as cliente:
        if consulta.isdigit():
            cid = int(consulta)
        else:
            respuesta = await cliente.get(
                f"{PUBCHEM}/compound/name/{quote(consulta)}/cids/JSON"
            )
            if respuesta.status_code == 404:
                raise MoleculaNoEncontrada(
                    f"PubChem no conoce «{consulta}». Prueba con el nombre en "
                    "inglés (caffeine, glucose) o con el CID"
                )
            respuesta.raise_for_status()
            cid = int(respuesta.json()["IdentifierList"]["CID"][0])
        sdf = await cliente.get(
            f"{PUBCHEM}/compound/cid/{cid}/SDF", params={"record_type": "3d"}
        )
        if sdf.status_code == 404:
            raise MoleculaNoEncontrada(
                f"PubChem no tiene conformación 3D para el CID {cid} (pasa con "
                "moléculas muy grandes, iones y metales)"
            )
        sdf.raise_for_status()
        propiedades = await cliente.get(
            f"{PUBCHEM}/compound/cid/{cid}/property/"
            "MolecularFormula,MolecularWeight,IUPACName,Title/JSON"
        )
        datos = {}
        if propiedades.status_code == 200:
            datos = propiedades.json()["PropertyTable"]["Properties"][0]
    atomos, enlaces = parsear_sdf(sdf.text)
    return {
        "nombre": datos.get("Title") or consulta,
        "atomos": atomos,
        "enlaces": enlaces,
        "fuente": {
            "origen": "pubchem",
            "detalle": f"PubChem CID {cid}, conformación 3D",
            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
        },
        "datos": {
            "cid": cid,
            "formula": datos.get("MolecularFormula") or formula_de(atomos),
            "masa_molar_g_mol": (
                float(datos["MolecularWeight"]) if datos.get("MolecularWeight") else None
            ),
            "nombre_iupac": datos.get("IUPACName"),
            "atomos": len(atomos),
            "enlaces": len(enlaces),
        },
    }


# --- Sin red: unas pocas, con la geometría calculada aquí ---------------------


def _agua() -> tuple[list[dict], list[dict]]:
    d, angulo = 0.9572, math.radians(104.52)
    medio = angulo / 2
    return (
        [
            {"elemento": "O", "posicion": [0.0, 0.0, 0.0]},
            {"elemento": "H", "posicion": [d * math.sin(medio), -d * math.cos(medio), 0.0]},
            {"elemento": "H", "posicion": [-d * math.sin(medio), -d * math.cos(medio), 0.0]},
        ],
        [{"a": 0, "b": 1, "orden": 1}, {"a": 0, "b": 2, "orden": 1}],
    )


def _metano() -> tuple[list[dict], list[dict]]:
    d = 1.087 / math.sqrt(3)
    vertices = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
    atomos = [{"elemento": "C", "posicion": [0.0, 0.0, 0.0]}] + [
        {"elemento": "H", "posicion": [d * x, d * y, d * z]} for x, y, z in vertices
    ]
    return atomos, [{"a": 0, "b": i, "orden": 1} for i in range(1, 5)]


def _co2() -> tuple[list[dict], list[dict]]:
    d = 1.16
    return (
        [
            {"elemento": "C", "posicion": [0.0, 0.0, 0.0]},
            {"elemento": "O", "posicion": [d, 0.0, 0.0]},
            {"elemento": "O", "posicion": [-d, 0.0, 0.0]},
        ],
        [{"a": 0, "b": 1, "orden": 2}, {"a": 0, "b": 2, "orden": 2}],
    )


def _amoniaco() -> tuple[list[dict], list[dict]]:
    d, angulo = 1.012, math.radians(106.67)
    # Tres H a la misma distancia del N y con el mismo ángulo H-N-H entre sí:
    # el ángulo con el eje vertical sale de cos(HNH) = 1 − 1,5·sin²(β).
    beta = math.asin(math.sqrt((1 - math.cos(angulo)) / 1.5))
    atomos = [{"elemento": "N", "posicion": [0.0, 0.0, 0.0]}]
    for i in range(3):
        fi = 2 * math.pi * i / 3
        atomos.append(
            {
                "elemento": "H",
                "posicion": [
                    d * math.sin(beta) * math.cos(fi),
                    -d * math.cos(beta),
                    d * math.sin(beta) * math.sin(fi),
                ],
            }
        )
    return atomos, [{"a": 0, "b": i, "orden": 1} for i in range(1, 4)]


LOCALES = {
    "agua": ("Agua", _agua, "water"),
    "water": ("Agua", _agua, "water"),
    "h2o": ("Agua", _agua, "water"),
    "metano": ("Metano", _metano, "methane"),
    "methane": ("Metano", _metano, "methane"),
    "ch4": ("Metano", _metano, "methane"),
    "dioxido de carbono": ("Dióxido de carbono", _co2, "carbon dioxide"),
    "dióxido de carbono": ("Dióxido de carbono", _co2, "carbon dioxide"),
    "carbon dioxide": ("Dióxido de carbono", _co2, "carbon dioxide"),
    "co2": ("Dióxido de carbono", _co2, "carbon dioxide"),
    "amoniaco": ("Amoniaco", _amoniaco, "ammonia"),
    "amoníaco": ("Amoniaco", _amoniaco, "ammonia"),
    "ammonia": ("Amoniaco", _amoniaco, "ammonia"),
    "nh3": ("Amoniaco", _amoniaco, "ammonia"),
}


def local(consulta: str) -> dict | None:
    entrada = LOCALES.get(consulta.strip().lower())
    if entrada is None:
        return None
    nombre, construir, _ = entrada
    atomos, enlaces = construir()
    for atomo in atomos:
        atomo["posicion"] = [round(c, 4) for c in atomo["posicion"]]
    return {
        "nombre": nombre,
        "atomos": atomos,
        "enlaces": enlaces,
        "fuente": {
            "origen": "engine",
            "detalle": "Geometría calculada con longitudes y ángulos de enlace experimentales",
        },
        "datos": {
            "formula": formula_de(atomos),
            "atomos": len(atomos),
            "enlaces": len(enlaces),
        },
    }


def nombre_en_ingles(consulta: str) -> str:
    """Las locales se buscan en PubChem con su nombre en inglés."""
    entrada = LOCALES.get(consulta.strip().lower())
    return entrada[2] if entrada else consulta
