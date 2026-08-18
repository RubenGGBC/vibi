"""Los archivos de esta máquina, tal y como los ve Vibi.

Funciones normales y no herramientas MCP: el servidor las envuelve
(`system_mcp`), pero aquí no hay nada que dependa de él, y así se pueden probar
sin levantar un puerto.

Todo lo que sale de aquí lleva rutas absolutas del sistema real —`C:\\Users\\...`,
`/Users/...`— y no del contenedor donde vive Vibi. Es la mitad del sentido de
este módulo: que cuando el usuario diga «el archivo ese de Descargas» y Vibi
conteste con una ruta, sea una ruta que él pueda pegar en su explorador.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import proceso
from .fs_scope import FueraDeAlcance, permitida, resolver

# Un directorio con veinte mil archivos no le sirve a nadie entero, y llenaría
# el contexto del modelo con nombres.
MAX_ENTRADAS = 400
MAX_RESULTADOS = 200

# Lo que se busca antes de rendirse y contar lo que se lleve. `MAX_RESULTADOS`
# no basta como freno: solo corta cuando hay coincidencias, y una búsqueda que
# no encuentra nada —`*zemu*` en el perfil entero— recorre el disco entero sin
# parar. Al otro lado está `agy`, que cancela la llamada al minuto y deja la
# conversación inservible, así que aquí hay que rendirse antes que él.
BUSQUEDA_SEGUNDOS = 45

# Lo que cabe en una lectura. Por encima hay que pedir un tramo con `desde`.
MAX_LECTURA_CHARS = 60_000

# Cuánto se mira de un archivo antes de decidir que no es texto. Un ejecutable
# tiene bytes nulos en los primeros compases; un fuente, nunca.
MUESTRA_BINARIO = 8_000


class ErrorArchivo(Exception):
    pass


def _entrada(ruta: Path) -> dict:
    try:
        info = ruta.stat()
    except OSError:
        return {"nombre": ruta.name, "tipo": "?", "bytes": 0, "modificado": 0.0}
    return {
        "nombre": ruta.name,
        "tipo": "carpeta" if ruta.is_dir() else "archivo",
        "bytes": info.st_size,
        "modificado": info.st_mtime,
    }


def listar(ruta: object, base: Path | None = None) -> dict:
    """Lo que hay en una carpeta."""
    destino = resolver(ruta, base)
    if not destino.exists():
        raise ErrorArchivo(f"No existe: {destino}")
    if not destino.is_dir():
        raise ErrorArchivo(f"No es una carpeta: {destino}")

    entradas: list[dict] = []
    truncado = False
    try:
        hijos = sorted(destino.iterdir(), key=lambda item: item.name.lower())
    except OSError as error:
        raise ErrorArchivo(f"No se puede leer {destino}: {error}") from error

    for hijo in hijos:
        # Los sitios vetados no se listan siquiera. Enseñar el nombre de algo
        # que después no se puede abrir solo invita a intentarlo.
        if not permitida(hijo):
            continue
        if len(entradas) >= MAX_ENTRADAS:
            truncado = True
            break
        entradas.append(_entrada(hijo))

    return {"ruta": str(destino), "entradas": entradas, "truncado": truncado}


def _es_binario(destino: Path) -> bool:
    try:
        with destino.open("rb") as handle:
            return b"\0" in handle.read(MUESTRA_BINARIO)
    except OSError:
        return False


def leer(
    ruta: object,
    desde: int = 1,
    lineas: int | None = None,
    base: Path | None = None,
) -> dict:
    """El contenido de un archivo de texto, numerado.

    Los números no son adorno: son lo que permite hablar de «la línea 40» al
    pedir un cambio, y lo que hace que `editar` reciba un fragmento copiado
    tal cual en vez de reconstruido de memoria.
    """
    destino = resolver(ruta, base)
    if not destino.exists():
        raise ErrorArchivo(f"No existe: {destino}")
    if destino.is_dir():
        raise ErrorArchivo(f"Es una carpeta, no un archivo: {destino}")
    if _es_binario(destino):
        raise ErrorArchivo(
            f"{destino} no es texto. Su tamaño y su fecha los da `listar`; para "
            f"algo más hace falta un programa que lo entienda."
        )

    try:
        contenido = destino.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ErrorArchivo(f"No se puede leer {destino}: {error}") from error

    todas = contenido.splitlines()
    inicio = max(1, int(desde or 1))
    fin = len(todas) if lineas is None else min(len(todas), inicio - 1 + int(lineas))
    tramo = todas[inicio - 1:fin]

    numeradas: list[str] = []
    gastado = 0
    cortado = fin < len(todas)
    for indice, linea in enumerate(tramo, start=inicio):
        pintada = f"{indice}\t{linea}"
        if gastado + len(pintada) > MAX_LECTURA_CHARS:
            cortado = True
            break
        numeradas.append(pintada)
        gastado += len(pintada) + 1

    return {
        "ruta": str(destino),
        "contenido": "\n".join(numeradas),
        "lineas_totales": len(todas),
        "desde": inicio,
        "hasta": inicio + len(numeradas) - 1 if numeradas else inicio,
        "truncado": cortado,
    }


def escribir(ruta: object, contenido: str, base: Path | None = None) -> dict:
    """Crea o reemplaza un archivo entero.

    Crea las carpetas que falten: pedir un archivo en una ruta nueva y que
    falle por el directorio intermedio obliga a un `mkdir` por el shell que no
    aporta nada.
    """
    destino = resolver(ruta, base)
    if destino.is_dir():
        raise ErrorArchivo(f"Es una carpeta, no un archivo: {destino}")

    texto = "" if contenido is None else str(contenido)
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
    except OSError as error:
        raise ErrorArchivo(f"No se puede escribir {destino}: {error}") from error

    return {
        "ruta": str(destino),
        "bytes": len(texto.encode("utf-8")),
        "lineas": len(texto.splitlines()),
    }


def editar(
    ruta: object, buscar: str, reemplazar: str, base: Path | None = None
) -> dict:
    """Cambia un fragmento exacto por otro.

    Es la operación que hace usable todo lo demás. Sin ella, tocar una línea de
    un archivo de mil obliga a reescribirlo entero, y lo que el modelo no vuelve
    a mirar antes de escribirlo se lo acaba inventando.

    Exige que el fragmento aparezca **una sola vez**. Con dos no hay forma de
    saber cuál querías, y elegir la primera es acertar la mitad de las veces en
    silencio: mejor devolver cuántas hay y que se pida con más contexto
    alrededor.
    """
    destino = resolver(ruta, base)
    if not destino.exists():
        raise ErrorArchivo(f"No existe: {destino}")

    viejo = str(buscar or "")
    if not viejo:
        raise ErrorArchivo("No has dicho qué fragmento cambiar")

    try:
        contenido = destino.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ErrorArchivo(f"No se puede leer {destino}: {error}") from error

    apariciones = contenido.count(viejo)
    if apariciones == 0:
        raise ErrorArchivo(
            f"Ese fragmento no está en {destino}. Léelo otra vez y copia el "
            f"texto exacto, con sus espacios."
        )
    if apariciones > 1:
        raise ErrorArchivo(
            f"Ese fragmento aparece {apariciones} veces en {destino}. Añade "
            f"líneas de alrededor hasta que sea único."
        )

    nuevo = contenido.replace(viejo, str(reemplazar or ""))
    try:
        destino.write_text(nuevo, encoding="utf-8")
    except OSError as error:
        raise ErrorArchivo(f"No se puede escribir {destino}: {error}") from error

    return {"ruta": str(destino), "lineas": len(nuevo.splitlines())}


def _rg() -> str | None:
    return shutil.which("rg")


def _buscar_contenido_rg(
    binario: str,
    texto: str,
    carpeta: Path,
    patron: str,
    limite_segundos: float = BUSQUEDA_SEGUNDOS,
) -> list[dict]:
    argv = [binario, "--line-number", "--no-heading", "--color", "never",
            "--max-count", "5", texto]
    if patron:
        argv += ["--glob", patron]
    argv.append(str(carpeta))
    try:
        completado = subprocess.run(  # noqa: S603 - argv es nuestro
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            # Eran 60, justo el corte de `agy`: la cancelación llegaba a la vez
            # que la respuesta y ganaba siempre la cancelación.
            timeout=max(1.0, limite_segundos),
            stdin=subprocess.DEVNULL,
            **proceso.sin_ventana(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    hallazgos: list[dict] = []
    for linea in completado.stdout.splitlines():
        # ripgrep separa con dos puntos, y en Windows la ruta trae uno propio
        # detrás de la letra de unidad: hay que partir por la derecha.
        partes = linea.rsplit(":", 2)
        if len(partes) != 3:
            continue
        archivo, numero, contenido = partes
        if not permitida(Path(archivo)):
            continue
        hallazgos.append(
            {"ruta": archivo, "linea": int(numero) if numero.isdigit() else 0,
             "texto": contenido.strip()[:300]}
        )
        if len(hallazgos) >= MAX_RESULTADOS:
            break
    return hallazgos


def _buscar_contenido_python(
    texto: str, carpeta: Path, patron: str, fin: float | None = None
) -> list[dict]:
    """El plan B cuando no hay ripgrep. Más lento y con el mismo resultado.

    Más lento importa aquí: sin `fin` es el que más fácil se pasa del minuto
    que `agy` aguanta, porque abre y lee cada archivo.
    """
    hallazgos: list[dict] = []
    for raiz, carpetas, archivos in os.walk(carpeta):
        if fin is not None and time.monotonic() >= fin:
            return hallazgos
        carpetas[:] = [
            nombre for nombre in carpetas
            if not nombre.startswith(".") and permitida(Path(raiz) / nombre)
        ]
        for nombre in archivos:
            if fin is not None and time.monotonic() >= fin:
                return hallazgos
            candidato = Path(raiz) / nombre
            if patron and not fnmatch.fnmatch(nombre, patron):
                continue
            if not permitida(candidato):
                continue
            try:
                with candidato.open("r", encoding="utf-8", errors="ignore") as handle:
                    for numero, linea in enumerate(handle, start=1):
                        if texto in linea:
                            hallazgos.append(
                                {"ruta": str(candidato), "linea": numero,
                                 "texto": linea.strip()[:300]}
                            )
                            break
            except OSError:
                continue
            if len(hallazgos) >= MAX_RESULTADOS:
                return hallazgos
    return hallazgos


def buscar(
    patron: str = "",
    ruta: object = None,
    texto: str = "",
    base: Path | None = None,
    limite_segundos: float = BUSQUEDA_SEGUNDOS,
) -> dict:
    """Busca por nombre, por contenido, o por los dos a la vez.

    Sin `texto` es un glob de nombres. Con él busca dentro, y `patron` pasa a
    ser el filtro de qué archivos mirar.

    `limite_segundos` es un fondo de saco, no una precisión: se comprueba entre
    archivo y archivo. Al agotarse devuelve lo que lleve encontrado con un
    aviso, que le sirve más al modelo que un error —para saber si algo está
    instalado, lo que salga en los primeros segundos suele bastar—.
    """
    carpeta = resolver(ruta or Path.home(), base)
    if not carpeta.is_dir():
        raise ErrorArchivo(f"No es una carpeta: {carpeta}")

    fin = time.monotonic() + max(0.0, limite_segundos)

    def _aviso(resultado: dict) -> dict:
        resultado["truncado"] = True
        resultado["aviso"] = (
            f"He estado {limite_segundos:.0f}s mirando y he parado aquí, así "
            f"que esto no es todo lo que hay. Acota la búsqueda a una carpeta "
            f"concreta en vez de al perfil entero."
        )
        return resultado

    if texto:
        binario = _rg()
        hallazgos = (
            _buscar_contenido_rg(binario, texto, carpeta, patron, limite_segundos)
            if binario
            else _buscar_contenido_python(texto, carpeta, patron, fin)
        )
        resultado = {
            "carpeta": str(carpeta),
            "coincidencias": hallazgos,
            "truncado": len(hallazgos) >= MAX_RESULTADOS,
        }
        return _aviso(resultado) if time.monotonic() >= fin else resultado

    if not patron:
        raise ErrorArchivo("Dime un patrón de nombre o un texto que buscar")

    encontrados: list[str] = []
    agotado = False
    try:
        for candidato in carpeta.rglob(patron):
            if time.monotonic() >= fin:
                agotado = True
                break
            if not permitida(candidato):
                continue
            encontrados.append(str(candidato))
            if len(encontrados) >= MAX_RESULTADOS:
                break
    except OSError as error:
        raise ErrorArchivo(f"No se puede buscar en {carpeta}: {error}") from error

    resultado = {
        "carpeta": str(carpeta),
        "archivos": encontrados,
        "truncado": len(encontrados) >= MAX_RESULTADOS,
    }
    return _aviso(resultado) if agotado else resultado


__all__ = [
    "ErrorArchivo",
    "FueraDeAlcance",
    "buscar",
    "editar",
    "escribir",
    "leer",
    "listar",
]
