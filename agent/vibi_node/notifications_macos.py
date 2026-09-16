"""Lo que macOS te está notificando, leído desde aquí.

La mitad de Windows la hace `notifications_windows` con una API pensada para
esto. **macOS no presta ninguna.** No hay equivalente de
`UserNotificationListener`: que una aplicación lea las notificaciones de las
demás no es algo que el sistema ofrezca. Lo único que queda es la base de datos
que `usernoted` va escribiendo por su cuenta, y de ahí salen las tres rarezas
de este módulo.

**Los textos no están en columnas.** Cada fila lleva un *binary plist* en
`data` y dentro, bajo `req`, el título (`titl`), el subtítulo (`subt`) y el
cuerpo (`body`). El subtítulo no es decoración: en un grupo de WhatsApp el
título es el grupo y el subtítulo es quién habla, así que tirarlo dejaría
«Cena del viernes: yo llevo el postre» sin decir quién lo lleva.

**La identidad es el UUID, no el número de fila.** Ver `Aviso` en
`notifications_comun`: `rec_id` se recicla y usarlo de clave hace desaparecer
avisos recién llegados.

**El permiso no se pide, se comprueba.** La base está detrás de Acceso a disco
completo, que solo se concede a mano en Ajustes del Sistema; no hay diálogo que
lanzar desde aquí. Así que `disponible()` intenta abrirla, que es la única
forma de preguntar, y `pedir_permiso()` no puede hacer más que abrir el panel.
"""
from __future__ import annotations

import datetime
import logging
import plistlib
import sqlite3
import subprocess
from pathlib import Path

from . import proceso

from .notifications_comun import (  # noqa: F401 - se reexportan a propósito
    APP_DESCONOCIDA,
    INTERVALO,
    MAX_VISTAS,
    Aviso,
    ErrorNotificaciones,
    Vigia,
)

log = logging.getLogger("vibi.node.notifications_macos")

RUTA = "~/Library/Group Containers/group.com.apple.usernoted/db2/db"

# Apple cuenta los segundos desde 2001, no desde 1970. Sin esto las fechas
# salen treinta y un años cortas.
EPOCA_APPLE = 978_307_200

# El panel exacto de Ajustes del Sistema donde se concede el permiso. Llevar al
# usuario a la lista concreta evita el «está en Privacidad, busca tú».
PANEL_DISCO = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
)


# Qué decirle al usuario cuando la base no se deja abrir. Vive aquí, junto al
# permiso del que habla, y no en `avisos`, que no tiene por qué saber que en
# este sistema el permiso se llama así ni dónde se concede.
AYUDA_PERMISO = (
    "Concédele a Vibi Acceso a disco completo en Ajustes del Sistema → "
    "Privacidad y seguridad → Acceso a disco completo, y reinicia Vibi. "
    "macOS no deja pedirlo desde dentro."
)


def _ruta_base() -> Path:
    return Path(RUTA).expanduser()


def _cuando(crudo: object) -> str:
    """De los segundos de Apple a una fecha que se entienda fuera."""
    try:
        segundos = float(crudo) + EPOCA_APPLE  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    return datetime.datetime.fromtimestamp(
        segundos, datetime.timezone.utc
    ).isoformat()


def _textos(datos: object) -> tuple[str, str]:
    """Del plist de la fila al título y al cuerpo.

    El subtítulo se pega delante del cuerpo en vez de ir a un campo propio
    porque `Aviso` solo tiene dos huecos, y de los tres textos el que puede
    perderse sin que el aviso deje de entenderse es el título, no quién habla.
    """
    peticion = plistlib.loads(bytes(datos)).get("req") or {}  # type: ignore[arg-type]
    titulo = str(peticion.get("titl") or "").strip()
    partes = [
        str(peticion.get(clave) or "").strip() for clave in ("subt", "body")
    ]
    return titulo, ": ".join(p for p in partes if p)


def _nombre_de_app(identificador: str, cache: dict[str, str]) -> str:
    """De `com.hnc.Discord` a `Discord`, preguntándole a Spotlight.

    Merece la pena porque este texto acaba en boca de Vibi: el servidor pasa
    `app` al modelo tal cual. Que te diga «te escriben por com.hnc.Discord» es
    peor que no decir la aplicación.

    Se cachea porque son siempre las mismas cuatro aplicaciones sondeadas cada
    segundo y medio, y si Spotlight no lo encuentra se devuelve el identificador
    —feo, pero cierto—.
    """
    if identificador in cache:
        return cache[identificador]
    nombre = identificador
    try:
        salida = subprocess.run(
            [
                "mdfind",
                f"kMDItemCFBundleIdentifier == '{identificador}'",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            **proceso.sin_ventana(),
        ).stdout.splitlines()
        if salida:
            nombre = Path(salida[0]).stem
    except (OSError, subprocess.SubprocessError):
        pass
    cache[identificador] = nombre
    return nombre


def _conectar(ruta: Path) -> sqlite3.Connection:
    """Abre la base en solo lectura.

    Solo lectura no es cortesía: la está escribiendo `usernoted` ahora mismo y
    esto la sondea cada segundo y medio. Que un fallo aquí no pueda tocar el
    centro de notificaciones del usuario lo garantiza el modo, no la intención.
    """
    return sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)


def disponible(ruta: Path | None = None) -> bool:
    """Si este Mac deja leer sus notificaciones ahora mismo.

    Que la base se abra equivale a tener Acceso a disco completo: es la única
    forma de comprobarlo, porque no hay API que responda a esa pregunta.
    """
    try:
        con = _conectar(ruta or _ruta_base())
    except sqlite3.Error:
        return False
    try:
        con.execute("SELECT 1 FROM record LIMIT 1")
        return True
    except sqlite3.Error:
        return False
    finally:
        con.close()


def pedir_permiso() -> bool:
    """Abre el panel donde se concede, porque no hay forma de pedirlo.

    Devuelve si ya estaba concedido. Nunca devuelve `True` por haber abierto el
    panel: el usuario tiene que arrastrar la aplicación a la lista y reiniciarla,
    y hasta que eso pase aquí no se lee nada.
    """
    if disponible():
        return True
    try:
        subprocess.run(
            ["open", PANEL_DISCO], check=False, timeout=5, **proceso.sin_ventana()
        )
    except (OSError, subprocess.SubprocessError) as error:
        log.warning("No pude abrir el panel de Acceso a disco completo: %s", error)
    return False


def leer(ruta: Path | None = None) -> list[Aviso]:
    """Todo lo que hay ahora mismo en el centro de notificaciones."""
    try:
        con = _conectar(ruta or _ruta_base())
    except sqlite3.Error as error:
        raise ErrorNotificaciones(
            "No pude abrir el centro de notificaciones. Concédele a Vibi "
            "Acceso a disco completo en Ajustes del Sistema."
        ) from error
    try:
        filas = con.execute(
            "SELECT r.uuid, r.data, r.request_date, a.identifier "
            "FROM record r JOIN app a ON a.app_id = r.app_id"
        ).fetchall()
    except sqlite3.Error as error:
        raise ErrorNotificaciones(f"No pude leer el centro: {error}") from error
    finally:
        con.close()

    cache: dict[str, str] = {}
    avisos = []
    for uuid, datos, cuando, identificador in filas:
        # Una fila rara no puede dejar mudo al resto del centro: la base la
        # escribe el sistema y trae de todo, incluidas notificaciones que no
        # son texto.
        try:
            titulo, cuerpo = _textos(datos)
        except Exception as error:  # noqa: BLE001
            log.debug("Fila ilegible en el centro de notificaciones: %s", error)
            continue
        if not titulo and not cuerpo:
            continue
        avisos.append(
            Aviso(
                id=bytes(uuid).hex(),
                app=_nombre_de_app(str(identificador or ""), cache)
                or APP_DESCONOCIDA,
                titulo=titulo,
                cuerpo=cuerpo,
                cuando=_cuando(cuando),
            )
        )
    return avisos


def diagnostico(ruta: Path | None = None) -> str:
    """Qué ve este módulo en la base de verdad, para confirmarlo a mano.

    Existe porque las pruebas van contra una base fabricada: comprueban el
    descodificado, no que macOS guarde las notificaciones con esta forma. El
    esquema de `usernoted` no está documentado por Apple y ha cambiado entre
    versiones, así que la única confirmación honesta es mirar la del sistema.

    Se ejecuta con `python -m vibi_node.notifications_macos`.
    """
    ruta = ruta or _ruta_base()
    lineas = [f"Base: {ruta}"]
    if not ruta.exists():
        return "\n".join([*lineas, "No existe. ¿Es este un Mac con notificaciones?"])
    try:
        avisos = leer(ruta)
    except ErrorNotificaciones:
        return "\n".join([*lineas, f"No se deja leer. {AYUDA_PERMISO}"])

    lineas.append(f"Notificaciones leídas: {len(avisos)}")
    if not avisos:
        lineas.append(
            "La base se abre pero está vacía: el esquema puede haber cambiado. "
            "Compruébalo con una notificación recién llegada."
        )
    for aviso in avisos[:5]:
        lineas.append(f"  {aviso}")
    return "\n".join(lineas)


if __name__ == "__main__":
    print(diagnostico())
