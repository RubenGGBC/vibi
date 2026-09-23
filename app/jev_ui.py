"""Manejar una ventana con Jev: el árbol de accesibilidad como opciones.

Es el bucle de `awlevin/typesafe-computer-use` sobre la percepción que Vibi ya
tenía. Allí se lee la pantalla con OCR; aquí se lee el árbol podado de
`ui_tree`, que dice qué es cada cosa y trae su `ref`. En cada vuelta se le
pregunta a Jev, **en una sola petición**, dos cosas independientes:

  - qué toca hacer: pulsar, escribir uno de los textos dados, Intro, mover una
    lista… o nada, porque ya está hecho;
  - sobre cuál de las hojas de la ventana, nunca más de 255 (`ui_tree.hojas`).

Y se ejecuta en el nodo como un paso de lote, que ya sabe fijar la ventana,
comprobar que un `ref` sigue siendo el que era y releer para ver si el texto
entró de verdad.

**Jev no escribe.** Elige de listas cerradas, así que lo que haya que teclear
lo pone quien llama —el modelo de chat, que sí sabe redactar— en `textos`, y
Jev solo decide cuándo y dónde va cada uno. Es también lo que hace que el
árbol, que lo escribió cualquiera, no pueda llevarle a hacer nada que no
estuviera ya en las opciones.

**Por debajo del umbral no se decide nada.** El bucle para y devuelve el árbol
tal como quedó, con lo hecho hasta ahí y en qué dudó, y sigue el modelo de
chat con `devices_ui_batch`. Es la regla de todo lo que se apoya en Jev: el
peor caso es el comportamiento de antes. Ver `docs/modelo-de-decision.md`.
"""
from __future__ import annotations

from . import db, decisor, nodes

UMBRAL = decisor.UMBRAL

MAX_PASOS = 25
PASOS_POR_DEFECTO = 12

# Cuántos pasos anteriores se le cuentan en el estado. Los suficientes para que
# no vuelva a escribir lo que ya escribió; más solo es ruido en la pregunta.
MEMORIA = 8

# Las acciones que no necesitan elemento. El resto se hacen sobre la hoja que
# conteste la segunda pregunta.
SIN_ELEMENTO = frozenset({"hecho", "intro"})


class JevNoDisponible(Exception):
    pass


def acciones(textos: list[str]) -> dict[str, str]:
    """Las opciones de la primera pregunta. Excluyentes, o la confianza miente.

    Cada texto es una opción propia y no una acción «escribir» genérica: así
    la elección dice también *cuál*, y dos textos distintos no pueden leerse
    como la misma duda.
    """
    opciones = {
        "clic": "pulsar un elemento de la ventana: un botón, un enlace, una "
        "pestaña, una conversación, una opción de menú",
    }
    for indice, texto in enumerate(textos, 1):
        corto = texto if len(texto) <= 80 else texto[:80] + "…"
        opciones[f"escribir_{indice}"] = (
            f"escribir «{corto}» en un campo de texto de la ventana"
        )
    opciones.update({
        "intro": "pulsar Intro para enviar o confirmar lo que ya está escrito",
        "bajar": "desplazar hacia abajo una lista o panel para ver lo que "
        "no se ve todavía",
        "subir": "desplazar hacia arriba una lista o panel",
        "hecho": "nada más: el objetivo ya está cumplido en lo que se ve",
    })
    return opciones


def paso_de(accion: str, ref: str | None, textos: list[str]) -> dict:
    """Lo elegido, traducido a un paso del lote del nodo."""
    if accion == "clic":
        return {"accion": "clic", "ref": ref}
    if accion.startswith("escribir_"):
        return {
            "accion": "escribir",
            "ref": ref,
            "texto": textos[int(accion.split("_", 1)[1]) - 1],
        }
    if accion == "intro":
        return {"accion": "tecla", "tecla": "enter"}
    if accion in ("bajar", "subir"):
        return {
            "accion": "desplazar",
            "ref": ref,
            "direccion": "abajo" if accion == "bajar" else "arriba",
        }
    raise ValueError(accion)


def _reparto(eleccion: decisor.Eleccion, opciones: dict[str, str]) -> list[dict]:
    """Las tres más votadas, para contar en qué dudó."""
    mejores = sorted(
        eleccion.reparto.items(), key=lambda par: par[1], reverse=True
    )[:3]
    return [
        {"opcion": opciones.get(clave, clave), "p": round(p, 3)}
        for clave, p in mejores
    ]


async def _turno(
    user: dict, node: dict, argumentos: dict
) -> dict:
    outcome = await nodes.dispatch(
        user, node, "ui.jev", argumentos, queue_if_offline=False
    )
    resultado = outcome.get("resultado")
    if outcome["estado"] != "ok" or not isinstance(resultado, dict):
        detalle = resultado if isinstance(resultado, dict) else {}
        raise nodes.NodeError(
            detalle.get("error")
            or outcome.get("mensaje")
            or f"{node['nombre']} no pudo leer la ventana"
        )
    return resultado


async def manejar(
    user: dict,
    node: dict,
    objetivo: str,
    textos: list[str] | None = None,
    ventana: str = "",
    trastienda: bool = False,
    max_pasos: int = PASOS_POR_DEFECTO,
) -> dict:
    """El bucle entero: mirar, preguntar, hacer, hasta acabar o dudar."""
    if not decisor.disponible():
        raise JevNoDisponible(
            "Jev no está configurado (falta OPPER_API_KEY en el servidor). "
            "Usa devices_ui_batch."
        )
    textos = [t for t in (textos or []) if t]
    max_pasos = max(1, min(MAX_PASOS, int(max_pasos)))
    opciones_accion = acciones(textos)

    base = {"ventana": ventana, "trastienda": trastienda}
    estado = await _turno(user, node, base)
    base["handle"] = estado.get("handle") or 0

    pasos: list[dict] = []
    motivo = "tope_pasos"
    duda = None
    anterior = None

    for numero in range(1, max_pasos + 1):
        hojas = estado.get("opciones") or {}
        situacion = {
            "objetivo": objetivo,
            "ventana": estado.get("ventana", ""),
            "hecho_hasta_ahora": [
                f"{p['n']}. {p['que']} → {p['estado']}" for p in pasos[-MEMORIA:]
            ] or ["nada todavía"],
            "arbol": estado.get("arbol", ""),
        }
        preguntas = {
            "accion": decisor.eleccion(
                f"Para conseguir «{objetivo}», ¿qué hay que hacer ahora en "
                "esta ventana?",
                opciones_accion,
            ),
        }
        if len(hojas) >= 2:
            preguntas["elemento"] = decisor.eleccion(
                f"Para conseguir «{objetivo}», ¿sobre qué elemento de la "
                "ventana hay que actuar ahora?",
                hojas,
            )

        respuesta = await decisor.preguntar(situacion, preguntas)
        if respuesta is None:
            motivo = "sin_decisor"
            break
        accion = respuesta.eleccion("accion")
        if accion is None or accion.opcion not in opciones_accion:
            motivo = "sin_decisor"
            break

        elemento = respuesta.eleccion("elemento")
        ref = None
        confianza_elemento = 1.0
        if accion.opcion not in SIN_ELEMENTO:
            if elemento is not None and elemento.opcion in hojas:
                ref, confianza_elemento = elemento.opcion, elemento.confianza
            elif len(hojas) == 1:
                ref = next(iter(hojas))

        db.log_event(
            "decisor",
            user["id"],
            asunto="ui.jev",
            opciones=len(hojas),
            elegida=f"{accion.opcion}:{ref or ''}",
            confianza=round(min(accion.confianza, confianza_elemento), 4),
            aceptada=accion.seguro(UMBRAL) and confianza_elemento >= UMBRAL,
            ms=respuesta.ms,
        )

        if not accion.seguro(UMBRAL):
            motivo, duda = "duda", {
                "pregunta": "qué hacer",
                "confianza": round(accion.confianza, 3),
                "reparto": _reparto(accion, opciones_accion),
            }
            break
        if accion.opcion == "hecho":
            motivo = "hecho"
            break
        if accion.opcion not in SIN_ELEMENTO:
            if ref is None:
                motivo = "sin_opciones"
                break
            if confianza_elemento < UMBRAL:
                motivo, duda = "duda", {
                    "pregunta": f"sobre qué elemento ({accion.opcion})",
                    "confianza": round(confianza_elemento, 3),
                    "reparto": _reparto(elemento, hojas) if elemento else [],
                }
                break

        paso = paso_de(accion.opcion, ref, textos)
        que = opciones_accion[accion.opcion].split(":")[0]
        if ref:
            que = f"{accion.opcion} en {ref} ({hojas.get(ref, '')})"
        arbol_antes = estado.get("arbol")
        estado = await _turno(user, node, {**base, "paso": paso})
        # La ventana puede cambiar por el paso —un diálogo que se cierra y deja
        # delante el documento—, y la siguiente vuelta tiene que ir contra la
        # que el nodo está mirando ahora, no contra la del principio.
        base["handle"] = estado.get("handle") or 0
        if estado.get("handle"):
            base["ventana"] = ""
        hecho = estado.get("paso") or {}
        ok = hecho.get("estado") == "ok"
        pasos.append({
            "n": numero,
            "que": que,
            "confianza": round(min(accion.confianza, confianza_elemento), 3),
            "estado": "ok" if ok else "error",
            **({"via": hecho["via"]} if hecho.get("via") else {}),
            **({"error": hecho.get("detalle") or hecho.get("error")} if not ok else {}),
        })
        if not ok:
            motivo = "error_paso"
            break

        # La misma decisión otra vez sin que la ventana haya cambiado es un
        # bucle, no un plan: el clic no hace lo que Jev cree que hace.
        decision = (accion.opcion, ref)
        if decision == anterior and estado.get("arbol") == arbol_antes:
            motivo = "atascado"
            break
        anterior = decision

    return {
        "terminado": motivo == "hecho",
        "motivo": motivo,
        "pasos": pasos,
        **({"duda": duda} if duda else {}),
        "ventana": estado.get("ventana", ""),
        "arbol": estado.get("arbol", ""),
        "opciones_ofrecidas": len(estado.get("opciones") or {}),
        "opciones_en_la_ventana": estado.get("ofrecibles", 0),
    }
