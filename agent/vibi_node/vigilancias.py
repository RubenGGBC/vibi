"""Quedarse mirando algo en esta máquina y avisar solo cuando cambia.

Es la segunda cosa que el nodo dice sin que se lo pregunten, después de los
avisos, y sigue el mismo trato: **aquí no se decide nada**. La sonda mira, saca
un sello y lo compara con el de la vuelta anterior. Si es distinto, lo cuenta.
Si lo que cambió merece interrumpir al usuario lo decide el servidor, que es
donde vive la frase con la que se pidió la vigilancia.

**El sello es un hash, y el texto va aparte.** El hash sirve para comparar
barato aquí; lo que viaja al servidor es texto legible y recortado, porque el
modelo tiene que poder juzgar qué cambió y un hash no le dice nada.

**El antirrebote es lo que hace esto usable.** Una página real cambia sola sin
parar: un contador, un anuncio que rota, un reloj. Sin protección, la sonda
dispararía cada vuelta para siempre. Por eso un sello nuevo no cuenta como
novedad hasta que **se repite dos vueltas seguidas**: lo que parpadea se
descarta solo y lo que de verdad ha cambiado sobrevive un tic más.

**La primera mirada es muda**, igual que la del `Vigia` de los avisos. Al
suscribirse —o al reconectar— lo que hay en pantalla lleva ahí desde antes y no
es noticia. Fijar la línea base sin hablar es lo que evita que reconectar
suelte una tanda de novedades falsas.
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field

from .config import NodeConfig

log = logging.getLogger("vibi.node.vigilancias")

# Cada cuánto despierta el bucle a ver si a alguna vigilancia le toca. No es la
# cadencia de sondeo: cada vigilancia trae la suya y aquí solo se comprueba
# quién ha vencido.
TIC = 1.0

# Lo que se manda de texto por campo. Lo mismo que acepta el servidor: pasarse
# solo serviría para que lo recortara él.
MAX_DETALLE = 400

# Cuántas líneas de diferencia se cuentan. Un cambio útil se ve en tres o
# cuatro; mandar el árbol entero de una ventana sería meter miles de tokens en
# el contexto por cada vez que se mueve algo.
MAX_LINEAS_CAMBIO = 6

# Cuánto se espera tras un fallo de sondeo antes de volver a esa vigilancia.
# Más largo que su cadencia: si el puerto de depuración no contesta, insistir
# cada cinco segundos no lo arregla y llena el log.
ESPERA_TRAS_FALLO = 30.0

SONDAS = ("proceso", "archivo", "web", "ventana", "actividad")

# Lo que devuelve la sonda web cuando el selector ya no encuentra nada. Lleva
# un NUL delante para que ninguna página pueda escribir por su cuenta algo
# que se confunda con esto: una web que diga literalmente «ausente» no puede
# hacerle creer a la vigilancia que su elemento ha desaparecido.
AUSENTE = "\u0000ausente"

# El valor de `GetExitCodeProcess` mientras el proceso sigue vivo.
STILL_ACTIVE = 259


@dataclass
class Encargo:
    """Una vigilancia, con lo que esta máquina recuerda de ella."""

    id: str
    sonda: str
    parametros: dict
    intervalo: float
    # Lo último confirmado. `None` significa que aún no se ha mirado nunca, y
    # es lo que hace muda la primera vuelta.
    sello: str | None = None
    texto: str = ""
    # Un sello visto una sola vez, todavía sin confirmar. El antirrebote.
    candidato: str | None = None
    candidato_texto: str = ""
    # Actividad envía también su primera lectura estable: tras una reconexión
    # puede contener justo el final que ocurrió mientras el nodo estaba fuera.
    inicial_contada: bool = False
    proxima: float = 0.0
    fallos: int = 0

    def toca(self, ahora: float) -> bool:
        return ahora >= self.proxima

    def reprogramar(self, ahora: float, espera: float | None = None) -> None:
        self.proxima = ahora + (self.intervalo if espera is None else espera)


@dataclass
class Encargos:
    """Lo que esta máquina tiene que estar mirando ahora mismo.

    El servidor manda siempre la lista completa, así que reconciliar es
    quedarse con lo que sigue estando y **conservarle su sello**: si a una
    vigilancia que no ha cambiado le borráramos la memoria en cada mensaje,
    la vuelta siguiente parecería una novedad y avisaría de la nada.
    """

    _por_id: dict[str, Encargo] = field(default_factory=dict)

    def reemplazar(self, crudo: object) -> None:
        entrantes = crudo if isinstance(crudo, list) else []
        vistos: set[str] = set()
        for bruto in entrantes:
            if not isinstance(bruto, dict):
                continue
            encargo_id = str(bruto.get("id") or "")
            sonda = str(bruto.get("sonda") or "")
            if not encargo_id or sonda not in SONDAS:
                continue
            parametros = bruto.get("parametros")
            if not isinstance(parametros, dict):
                parametros = {}
            try:
                intervalo = max(1.0, float(bruto.get("intervalo") or 5.0))
            except (TypeError, ValueError):
                intervalo = 5.0

            vistos.add(encargo_id)
            ya = self._por_id.get(encargo_id)
            if ya is None:
                self._por_id[encargo_id] = Encargo(
                    id=encargo_id,
                    sonda=sonda,
                    parametros=parametros,
                    intervalo=intervalo,
                )
            else:
                ya.parametros = parametros
                ya.intervalo = intervalo

        for sobrante in set(self._por_id) - vistos:
            del self._por_id[sobrante]

    def pendientes(self, ahora: float) -> list[Encargo]:
        return [e for e in self._por_id.values() if e.toca(ahora)]

    def __len__(self) -> int:
        return len(self._por_id)


# ---------- Las sondas ----------

def _sello(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8", "ignore")).hexdigest()[:16]


def _recortar(texto: str) -> str:
    return " ".join(str(texto or "").split())[:MAX_DETALLE]


def _proceso_vivo_por_pid(pid: int) -> tuple[bool, int | None]:
    """Si ese proceso sigue vivo y, si se puede saber, con qué salió."""
    if sys.platform == "win32":
        import ctypes  # noqa: PLC0415 - solo en Windows

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            return False, None
        try:
            codigo = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(codigo)):
                return False, None
            if codigo.value == STILL_ACTIVE:
                return True, None
            return False, int(codigo.value)
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False, None
    except PermissionError:
        # Existe pero es de otro usuario: sigue vivo, que es lo que se pregunta.
        return True, None
    return True, None


def _proceso_vivo_por_nombre(nombre: str) -> bool:
    from . import proceso  # noqa: PLC0415 - solo para el flag de consola

    if sys.platform == "win32":
        salida = subprocess.run(  # noqa: S603
            ["tasklist", "/FI", f"IMAGENAME eq {nombre}", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            **proceso.sin_ventana(),
        )
        return nombre.casefold() in (salida.stdout or "").casefold()

    salida = subprocess.run(  # noqa: S603
        ["pgrep", "-f", nombre], capture_output=True, text=True, timeout=10,
        **proceso.sin_ventana(),
    )
    return salida.returncode == 0


def _sondear_proceso(parametros: dict) -> tuple[str, str]:
    pid = parametros.get("pid")
    if pid:
        vivo, codigo = _proceso_vivo_por_pid(int(pid))
        if vivo:
            return "vivo", f"El proceso {pid} sigue en marcha"
        if codigo is None:
            return "muerto", f"El proceso {pid} ya no está"
        final = "sin errores" if codigo == 0 else f"con el código {codigo}"
        return f"muerto:{codigo}", f"El proceso {pid} ha terminado {final}"

    nombre = str(parametros.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("Una vigilancia de proceso necesita un pid o un nombre")
    if _proceso_vivo_por_nombre(nombre):
        return "vivo", f"«{nombre}» sigue en marcha"
    return "muerto", f"«{nombre}» ya no está en marcha"


def _sondear_archivo(parametros: dict) -> tuple[str, str]:
    from .fs_scope import resolver  # noqa: PLC0415 - solo cuando toca el disco

    ruta = resolver(parametros.get("ruta"))
    if not ruta.exists():
        return "ausente", f"Todavía no existe «{ruta}»"
    if not ruta.is_file():
        raise ValueError(f"No es un archivo: {ruta}")
    info = ruta.stat()
    # El tamaño no forma parte del sello: una descarga crece continuamente y
    # eso no es una novedad. Lo relevante es que la ruta aparezca o desaparezca.
    return "presente", f"Existe «{ruta}» y ocupa {info.st_size} bytes"


async def _sondear_web(parametros: dict) -> tuple[str, str]:
    from . import cdp, web_apps  # noqa: PLC0415 - solo cuando toca una web

    app = str(parametros.get("app") or "").strip()
    puerto = parametros.get("puerto")
    puerto = int(puerto) if puerto else web_apps.puerto_de(app)
    if not puerto:
        raise ValueError(f"No sé por dónde hablar con «{app}»")

    selector = str(parametros.get("selector") or "").strip()
    if selector:
        # Serializar el selector con JSON evita escapar a mano las comillas y
        # los corchetes de un selector CSS cualquiera.
        js = (
            f"(() => {{ const n = document.querySelector({json.dumps(selector)}); "
            f"return n ? (n.innerText || n.textContent || '') : "
            f"{json.dumps(AUSENTE)}; }})()"
        )
    else:
        js = "document.body ? document.body.innerText : ''"

    pista = str(parametros.get("pestana") or "").strip() or None
    valor, _pagina = await cdp.evaluar_en(puerto, pista, js)
    crudo = str(valor or "")
    # Se compara antes de normalizar: el centinela lleva un NUL delante justo
    # para que ninguna página pueda producirlo por accidente, y normalizar
    # primero lo dejaría indistinguible de un texto que dijera «ausente».
    if crudo == AUSENTE:
        return "ausente", f"Ya no está «{selector}» en la página"
    texto = " ".join(crudo.split())
    return _sello(texto), texto
def _sondear_ventana(parametros: dict) -> tuple[str, str]:
    from . import ui  # noqa: PLC0415 - solo cuando toca una ventana

    ventana = str(parametros.get("ventana") or "").strip() or None
    leido = ui.sello_de(ventana)
    if leido.get("vacio"):
        return "vacio", f"«{leido.get('ventana') or ventana}» no dice nada"
    arbol = str(leido.get("arbol") or "")
    return _sello(arbol), arbol


async def sondear(encargo: Encargo) -> tuple[str, str]:
    """Mira, y devuelve (sello, texto). Lo que falle sube como excepción."""
    if encargo.sonda == "proceso":
        return await asyncio.to_thread(_sondear_proceso, encargo.parametros)
    if encargo.sonda == "archivo":
        return await asyncio.to_thread(_sondear_archivo, encargo.parametros)
    if encargo.sonda == "web":
        return await _sondear_web(encargo.parametros)
    if encargo.sonda in {"ventana", "actividad"}:
        return await asyncio.to_thread(_sondear_ventana, encargo.parametros)
    raise ValueError(f"«{encargo.sonda}» no es una sonda que yo sepa hacer")


# ---------- Qué se cuenta de un cambio ----------

def resumen_cambio(antes: str, ahora: str) -> tuple[str, str]:
    """Solo lo que ha cambiado, no los dos textos enteros.

    El árbol de una ventana son miles de caracteres y el 99% es igual que hace
    cinco segundos. Mandarlo entero sería pagar el contexto del modelo por
    repetir lo que no ha pasado; lo que le sirve para juzgar son las líneas que
    aparecieron y las que se fueron.
    """
    viejas = antes.splitlines() or [antes]
    nuevas = ahora.splitlines() or [ahora]
    if len(viejas) <= 1 and len(nuevas) <= 1:
        return _recortar(antes), _recortar(ahora)

    fuera, dentro = [], []
    for linea in difflib.unified_diff(viejas, nuevas, n=0, lineterm=""):
        if linea.startswith("---") or linea.startswith("+++") or linea.startswith("@@"):
            continue
        if linea.startswith("-") and len(fuera) < MAX_LINEAS_CAMBIO:
            fuera.append(linea[1:].strip())
        elif linea.startswith("+") and len(dentro) < MAX_LINEAS_CAMBIO:
            dentro.append(linea[1:].strip())

    return (
        _recortar(" / ".join(p for p in fuera if p)),
        _recortar(" / ".join(p for p in dentro if p)),
    )


# ---------- El bucle ----------

async def _contar_novedad(
    connection, encargo: Encargo, antes: str, ahora: str
) -> None:
    resumen_antes, resumen_ahora = resumen_cambio(antes, ahora)
    await connection.send(
        json.dumps(
            {
                "tipo": "novedad",
                "vigilancia": encargo.id,
                "antes": resumen_antes,
                "ahora": resumen_ahora,
                "detalle": _recortar(ahora),
            }
        )
    )


async def _una_vuelta(connection, encargo: Encargo, ahora: float) -> bool:
    """Sondea una vigilancia. Devuelve si hay que seguir con la sesión."""
    try:
        sello, texto = await sondear(encargo)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - una sonda rota no calla al nodo
        encargo.fallos += 1
        # Un fallo también es información —la ventana se cerró, la aplicación
        # ya no escucha—, así que se trata como un sello más y pasa por el
        # mismo antirrebote. Así un tropiezo suelto de red no dispara nada,
        # pero una aplicación que se ha ido de verdad sí acaba contándose.
        sello = f"error:{type(error).__name__}"
        texto = f"No he podido mirar: {error}"
        encargo.reprogramar(ahora, ESPERA_TRAS_FALLO)
    else:
        encargo.fallos = 0
        encargo.reprogramar(ahora)

    # La primera mirada fija la línea base y no dice nada: lo que ya estaba ahí
    # cuando empezamos a mirar no es una novedad.
    if encargo.sello is None:
        encargo.sello, encargo.texto = sello, texto
        return True

    if sello == encargo.sello:
        encargo.candidato, encargo.candidato_texto = None, ""
        if encargo.sonda == "actividad" and not encargo.inicial_contada:
            encargo.inicial_contada = True
            try:
                await _contar_novedad(connection, encargo, "", texto)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                log.warning("No pude contar el estado inicial: %s", error)
                return False
        return True

    if encargo.candidato != sello:
        # Primera vez que se ve. Se espera otra vuelta a ver si se sostiene.
        encargo.candidato, encargo.candidato_texto = sello, texto
        return True

    antes = encargo.texto
    encargo.sello, encargo.texto = sello, texto
    encargo.candidato, encargo.candidato_texto = None, ""
    encargo.inicial_contada = True
    try:
        await _contar_novedad(connection, encargo, antes, texto)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001
        log.warning("No pude contar una novedad: %s", error)
        return False
    return True


async def vigilar(connection, config: NodeConfig, encargos: Encargos) -> None:
    """Sondea lo que haya encargado hasta que corten la sesión.

    Vive mientras vive la conexión, igual que el vigía de los avisos: si se
    cae, lo que se recuerda de cada vigilancia se va con ella y al volver la
    primera mirada es muda otra vez. Es lo correcto —no sabemos qué pasó
    mientras no mirábamos— y el servidor se encarga de decírselo al usuario.
    """
    while True:
        ahora = time.monotonic()
        for encargo in encargos.pendientes(ahora):
            if not await _una_vuelta(connection, encargo, ahora):
                return
        await asyncio.sleep(TIC)
