"""Encontrar un archivo en el disco de alguien, en menos de un segundo.

Antes esto era una línea: `raiz.rglob(patron)`. Medido sobre el histórico real
de este equipo, esa línea daba una **mediana de 300 segundos** y cuatro
búsquedas caducadas de catorce. Se entiende: `rglob` desde la carpeta de un
usuario entra en `node_modules`, en `AppData`, en `$Recycle.Bin` y en todos los
`.git` del disco con el mismo interés que en la carpeta que le importa a quien
pregunta.

**Windows lleva un índice de eso desde hace veinte años**, y es el mismo que
usa el cuadro de búsqueda del explorador: se consulta con SQL a través del
proveedor `Search.CollatorDSO`. Medido aquí el 2026-08-20: **482 ms** para
treinta PDF de todo el disco, 514 ms buscando por trozo de nombre, 2,7 s para
`*.py` —el peor caso, porque hay decenas de miles—. Frente a los 300 s de
antes, es entre cien y seiscientas veces más rápido, y además busca en todo el
disco en vez de en una rama.

El recorrido no se tira: sigue como repliegue para lo que el índice no cubre
—una carpeta excluida, un disco externo recién enchufado, un Mac, el servicio
de búsqueda parado—. Pero ahora con las dos cosas que le faltaban: **poda** de
lo que nunca interesa y **un reloj**, para que el peor caso sea una respuesta
pobre y no una espera de cinco minutos.
"""
from __future__ import annotations

import fnmatch
import platform
import time
from pathlib import Path

# Lo que no se mira nunca al recorrer. No es una lista de gustos: son
# directorios que multiplican el trabajo por mil y donde nadie guarda «lo que
# me bajé» ni «el proyecto ese». Un `node_modules` cualquiera tiene más
# archivos que toda la carpeta de documentos de una persona.
NUNCA = frozenset({
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache",
    ".gradle", ".cargo", ".rustup", ".npm", ".cache", ".next", ".nuxt",
    "appdata", "windows", "$recycle.bin", "system volume information",
    "programdata", "$windows.~ws", "onedrivetemp",
})

# Cuánto puede durar un recorrido antes de devolver lo que lleve. Va muy por
# debajo del timeout del nodo (45 s) a propósito: media respuesta a tiempo vale
# más que una completa que llega cuando ya nadie la espera.
PRESUPUESTO_RECORRIDO = 8.0

# Cada cuántos archivos se mira el reloj. Preguntar la hora en cada uno cuesta
# más que el propio `stat` en un directorio grande.
CADA_CUANTO_SE_MIRA_EL_RELOJ = 200


def se_salta(nombre: str) -> bool:
    """Si este directorio no se recorre.

    Lo oculto entero se salta: en un disco de trabajo, una carpeta que empieza
    por punto es configuración o caché de alguna herramienta, nunca lo que
    alguien te está pidiendo que busques.
    """
    plano = (nombre or "").casefold()
    if plano in NUNCA:
        return True
    return plano.startswith(".") and plano not in (".", "..")


def patron_a_like(patron: str) -> str:
    """De lo que escribe una persona a lo que entiende el índice.

    Dos formas conviven porque las dos son naturales: «factura» es *que
    contenga factura*, y `*.pdf` es un comodín de toda la vida. El `%` y el `_`
    de SQL se escapan primero, porque si no, un archivo llamado «50% descuento»
    se convertiría en una consulta que devuelve el disco entero.
    """
    crudo = str(patron or "").strip()
    if not crudo:
        return "%"
    # El escape va antes de traducir los comodines nuestros, o se escaparían
    # los que acabamos de poner.
    escapado = crudo.replace("'", "''").replace("%", "[%]").replace("_", "[_]")
    if "*" in crudo or "?" in crudo:
        return escapado.replace("*", "%").replace("?", "_")
    return f"%{escapado}%"


def ruta_de_url(url: str) -> str:
    """De `file:C:/Users/rebel/x.pdf` a la ruta que entiende el disco.

    El índice devuelve las rutas en forma de URL con barras normales. No es una
    URL de verdad —no viene percent-encoded—, así que no hay que decodificar
    nada: basta quitarle el esquema y enderezar las barras.
    """
    crudo = str(url or "")
    if crudo.lower().startswith("file:"):
        crudo = crudo[5:].lstrip("/")
    return crudo.replace("/", "\\")


def _fila(ruta: Path) -> dict | None:
    try:
        info = ruta.stat()
    except OSError:
        return None
    return {
        "ruta": str(ruta),
        "nombre": ruta.name,
        "directorio": ruta.is_dir(),
        "bytes": info.st_size if ruta.is_file() else None,
        "modificado_en": info.st_mtime,
    }


# ---------- El índice de Windows ----------

def indice_disponible() -> bool:
    return platform.system() == "Windows"


def por_indice(
    patron: str, raiz: Path | None, limite: int
) -> dict | None:
    """Consulta el índice del sistema. `None` si no se puede usar.

    Devolver `None` y no lanzar es deliberado: que el índice no esté no es un
    error que deba ver nadie, es una condición normal —un disco recién
    enchufado, el servicio parado, una carpeta excluida a mano—. Lo que toca
    entonces es recorrer, no dar un fallo.
    """
    if not indice_disponible():
        return None
    try:
        import comtypes.client as cliente
    except ImportError:
        return None

    condiciones = [f"System.FileName LIKE '{patron_a_like(patron)}'"]
    if raiz is not None:
        # `SCOPE` acota al subárbol, en la forma de URL que quiere el índice.
        carpeta = str(raiz).replace("'", "''").replace("\\", "/")
        condiciones.append(f"SCOPE = 'file:{carpeta}'")
    # **`System.ItemUrl` y no `System.ItemPathDisplay`.** El segundo es el
    # nombre *para enseñar*, con las carpetas del sistema traducidas al idioma
    # de Windows: en esta máquina devuelve `C:\\Usuarios\\rebel\\Descargas\\…`,
    # que no existe en el disco —la ruta real es `C:\\Users\\rebel\\Downloads`—.
    # Con él, cada resultado moría en el `stat()` y la búsqueda salía vacía
    # habiendo encontrado los archivos. Costó encontrarlo porque el síntoma es
    # «el índice no tiene nada», no un error.
    consulta = (
        f"SELECT TOP {int(limite)} System.ItemUrl "
        f"FROM SystemIndex WHERE {' AND '.join(condiciones)}"
    )

    conexion = None
    try:
        conexion = cliente.CreateObject("ADODB.Connection")
        conexion.Open(
            'Provider=Search.CollatorDSO;'
            'Extended Properties="Application=Windows"'
        )
        registros = cliente.CreateObject("ADODB.Recordset")
        registros.Open(consulta, conexion)
        rutas = []
        while not registros.EOF and len(rutas) < limite:
            valor = registros.Fields[0].Value
            if valor:
                rutas.append(ruta_de_url(str(valor)))
            registros.MoveNext()
        registros.Close()
    except Exception:
        return None
    finally:
        try:
            if conexion is not None:
                conexion.Close()
        except Exception:
            pass

    encontrados = [f for f in (_fila(Path(r)) for r in rutas) if f]
    return {
        "resultados": encontrados,
        "total": len(encontrados),
        "truncado": len(encontrados) >= limite,
        "raiz": str(raiz) if raiz else "todo el disco",
        "via": "índice del sistema",
        "agotado": False,
    }


# ---------- El recorrido, para lo que el índice no cubre ----------

def por_recorrido(
    patron: str, raiz: Path, limite: int, presupuesto: float
) -> dict:
    """Baja por el árbol podando y con reloj, y devuelve lo que haya dado tiempo.

    `os.walk` en vez de `rglob` porque hace falta poder **no bajar** por un
    directorio: `rglob` ya se ha metido dentro cuando te lo enseña, que es
    justo lo que costaba los minutos.
    """
    import os

    crudo = str(patron or "").strip() or "*"
    if "*" not in crudo and "?" not in crudo:
        # Sin comodines, «factura» significa que lo contenga, igual que arriba.
        casa = lambda nombre: crudo.casefold() in nombre.casefold()  # noqa: E731
    else:
        plano = crudo.casefold()
        casa = lambda nombre: fnmatch.fnmatch(nombre.casefold(), plano)  # noqa: E731

    fin = time.monotonic() + max(0.1, presupuesto)
    encontrados: list[dict] = []
    mirados = 0
    agotado = False

    for carpeta, subcarpetas, archivos in os.walk(str(raiz), topdown=True):
        # `topdown=True` y modificar la lista en el sitio es lo que hace que
        # `os.walk` **no baje** por lo podado.
        subcarpetas[:] = [s for s in subcarpetas if not se_salta(s)]

        for nombre in archivos + subcarpetas:
            mirados += 1
            if mirados % CADA_CUANTO_SE_MIRA_EL_RELOJ == 0:
                if time.monotonic() > fin:
                    agotado = True
                    break
            if not casa(nombre):
                continue
            fila = _fila(Path(carpeta) / nombre)
            if fila is None:
                continue
            encontrados.append(fila)
            if len(encontrados) >= limite:
                break
        if agotado or len(encontrados) >= limite:
            break
        if time.monotonic() > fin:
            agotado = True
            break

    return {
        "resultados": encontrados,
        "total": len(encontrados),
        "truncado": len(encontrados) >= limite,
        "raiz": str(raiz),
        "via": "recorriendo el disco",
        "agotado": agotado,
    }


def buscar(patron: str, raiz: Path, limite: int) -> dict:
    """El índice si contesta, y el recorrido si no.

    Se pregunta al índice **primero y sin acotar la carpeta** cuando la raíz es
    la del usuario, porque ahí es donde el índice gana de largo. Si vuelve
    vacío se recorre igualmente: un índice que no ha visto un archivo no es lo
    mismo que un archivo que no existe, y quedarse en «no hay nada» sería el
    tipo de respuesta segura de sí misma que no vale.
    """
    del_indice = por_indice(patron, raiz, limite)
    if del_indice and del_indice["resultados"]:
        return del_indice

    recorrido = por_recorrido(patron, raiz, limite, PRESUPUESTO_RECORRIDO)
    if not recorrido["resultados"] and del_indice is not None:
        recorrido["via"] = "recorriendo el disco (el índice tampoco tenía nada)"
    return recorrido
