"""Un escritorio aparte donde Vibi trabaja sin que se le vea.

La idea es de Rubén y resuelve de raíz lo que llevábamos todo el día
parcheando. Windows sabe tener **varios escritorios de verdad** —el mecanismo
de la pantalla de Ctrl+Alt+Supr, no los de Win+Tab—, y cada uno tiene su propia
cola de teclado, su propio foco y sus propias ventanas. Una aplicación abierta
ahí **no existe** para quien está mirando la pantalla.

Lo que eso cambia: dentro de la trastienda, Vibi puede maximizar, hacer foco,
mover el ratón y teclear a gusto. Deja de tener que ser fina con el árbol de
accesibilidad para no molestar, y puede usar capturas y ratón, que es como
mejor se le da.

**Medido en este equipo el 2026-08-20, todo comprobado y no supuesto:**

* `CreateDesktop` y lanzar una aplicación dentro: funciona.
* No se ve desde el escritorio normal: confirmado, invisible.
* Un Chromium arranca ahí y **contesta por su puerto de depuración**: dos
  pestañas leídas desde fuera.
* Se puede **fotografiar** una ventana de ahí con `PrintWindow`, sin pantalla
  física: 1936x1048 capturados.
* **El sonido se comparte.** Reproducir algo en la trastienda se oye igual: el
  escritorio separa ventanas y entrada, no el audio.

**Y lo que NO se puede, que es la frontera del diseño:** una ventana **no se
traspasa** de un escritorio a otro. Probado con `SetParent`, `ShowWindow` y
`SetForegroundWindow`: ninguno la trae, y no hay API que lo haga. Una ventana
pertenece al escritorio donde nació.

De ahí sale la regla, y conviene tenerla clara antes de tocar nada:

    La trastienda es para el trabajo. El resultado se entrega en el
    escritorio del usuario.

* Si el resultado es **sonido**, ya está: se oye.
* Si es un **dato**, se cuenta y punto.
* Si es algo que **abrir** —un archivo, una web—, se abre al final en el
  escritorio de verdad. El trabajo sucio fue aquí; lo último, allí.
* Y si lo que se pide **es una ventana con la que va a trastear** —«ábreme el
  vídeo», «ponme el Word»—, eso **no entra aquí**: va directo a su escritorio,
  como siempre. Esconderlo sería lo contrario de lo que se pidió.

**Las apps de la Microsoft Store se quedan fuera.** Se lanzan a través del
explorador, que vive en el escritorio del usuario. WhatsApp y Spotify son de
ésas; para ellas queda su versión web dentro de un navegador de la trastienda.
"""
from __future__ import annotations

import ctypes
import platform
import threading
from ctypes import wintypes

# El nombre del escritorio. Se comparte entre procesos del agente, así que va
# fijo: dos trastiendas distintas serían dos sitios donde buscar.
NOMBRE = "VibiTrastienda"

# Permisos sobre el escritorio. `GENERIC_ALL` porque hay que crear ventanas,
# leerlas, enumerar y conmutar el hilo: recortarlo aquí solo da errores raros
# más adelante.
GENERIC_ALL = 0x10000000

# `CreateProcess` con `STARTUPINFO.lpDesktop` es **la única forma** de meter una
# aplicación en otro escritorio. No hay manera de mover un proceso ya arrancado,
# igual que no la hay de mover una ventana.
STARTF_USESHOWWINDOW = 0x00000001
SW_SHOWNORMAL = 1
CREATE_NEW_CONSOLE = 0x00000010


class ErrorTrastienda(Exception):
    pass


def disponible() -> bool:
    return platform.system() == "Windows"


# ---------- Los tipos de Win32 que hacen falta ----------

class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _user32():
    user32 = ctypes.windll.user32
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.CreateDesktopW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    ]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.OpenDesktopW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
    return user32


# ---------- El escritorio ----------

_candado = threading.Lock()
_handle = None


def abrir() -> int:
    """El escritorio de la trastienda, creándolo si aún no existe.

    Se guarda el handle porque **cerrarlo destruye el escritorio** cuando no
    queda nadie dentro, y con él todo lo que Vibi tuviera abierto. Vive lo que
    viva el agente.
    """
    global _handle
    if not disponible():
        raise ErrorTrastienda(
            "Los escritorios aparte son cosa de Windows. Aquí no hay trastienda."
        )
    with _candado:
        if _handle:
            return _handle
        user32 = _user32()
        handle = user32.OpenDesktopW(NOMBRE, 0, False, GENERIC_ALL)
        if not handle:
            handle = user32.CreateDesktopW(
                NOMBRE, None, None, 0, GENERIC_ALL, None
            )
        if not handle:
            codigo = ctypes.windll.kernel32.GetLastError()
            raise ErrorTrastienda(
                f"No se pudo abrir la trastienda (error {codigo})"
            )
        _handle = int(handle)
        return _handle


def existe() -> bool:
    """Si la trastienda está montada, sin montarla."""
    if not disponible():
        return False
    if _handle:
        return True
    user32 = _user32()
    handle = user32.OpenDesktopW(NOMBRE, 0, False, GENERIC_ALL)
    if not handle:
        return False
    user32.CloseDesktop(handle)
    return True


class dentro:
    """Un `with` que pone **este hilo** a trabajar en la trastienda.

    Sirve para un hilo limpio y **falla en uno que ya haya dibujado algo**:
    `SetThreadDesktop` devuelve `ERROR_BUSY` (170) si el hilo tiene alguna
    ventana o enganche, y UIA crea ventanas ocultas en cuanto se le pregunta
    algo. Medido: la primera lectura del árbol funciona y la siguiente ya no.

    Por eso lo normal es no usar esto directamente, sino `ejecutar()`, que
    manda el trabajo a un hilo que nació dentro y nunca ha salido.
    """

    def __init__(self):
        self.anterior = None
        self.user32 = None

    def __enter__(self):
        handle = abrir()
        self.user32 = _user32()
        kernel32 = ctypes.windll.kernel32
        self.anterior = self.user32.GetThreadDesktop(
            kernel32.GetCurrentThreadId()
        )
        if not self.user32.SetThreadDesktop(handle):
            codigo = kernel32.GetLastError()
            self.anterior = None
            raise ErrorTrastienda(
                f"No se pudo entrar en la trastienda desde este hilo (error "
                f"{codigo}). Pasa si el hilo ya ha creado alguna ventana; usa "
                "`trastienda.ejecutar()`, que tiene un hilo propio para esto."
            )
        return self

    def __exit__(self, *_):
        if self.anterior and self.user32:
            self.user32.SetThreadDesktop(self.anterior)
        return False


# ---------- El hilo que vive dentro ----------
#
# **Por qué hace falta un hilo dedicado y no basta con `dentro()`.**
# `SetThreadDesktop` falla con `ERROR_BUSY` en cuanto el hilo tiene una ventana,
# y UIA crea ventanas ocultas al primer uso. Medido el 2026-08-20: la primera
# lectura del árbol entraba bien y la segunda ya no. Un hilo que **nace** en la
# trastienda y no sale nunca no tiene ese problema, y de paso mantiene su propia
# instancia de UIA —que ya iba por hilo, ver `ui_windows._automation`—.
_cola: "queue.Queue | None" = None
_obrero: threading.Thread | None = None


def _bucle(preparado: threading.Event) -> None:
    try:
        handle = abrir()
        user32 = _user32()
        if not user32.SetThreadDesktop(handle):
            codigo = ctypes.windll.kernel32.GetLastError()
            raise ErrorTrastienda(
                f"El hilo de la trastienda no pudo entrar (error {codigo})"
            )
    except Exception as error:  # pragma: no cover - depende del sistema
        _bucle.fallo = error
        preparado.set()
        return

    _bucle.fallo = None
    preparado.set()
    while True:
        trabajo, respuesta = _cola.get()
        if trabajo is None:
            return
        try:
            respuesta.put((True, trabajo()))
        except BaseException as error:  # noqa: BLE001 - viaja al que pidió
            respuesta.put((False, error))
        finally:
            _cola.task_done()


_bucle.fallo = None


def ejecutar(trabajo):
    """Corre eso **dentro** de la trastienda y devuelve lo que dé.

    Todo lo que toque la trastienda —leer el árbol, teclear, fotografiar— tiene
    que pasar por aquí. Lo que se lanza es una función sin argumentos; si
    revienta, la excepción sale por donde se pidió, como si hubiera corrido
    aquí mismo.
    """
    import queue

    global _cola, _obrero
    with _candado:
        if _obrero is None or not _obrero.is_alive():
            _cola = queue.Queue()
            preparado = threading.Event()
            _obrero = threading.Thread(
                target=_bucle, args=(preparado,),
                name="vibi-trastienda", daemon=True,
            )
            _obrero.start()
            preparado.wait(timeout=10)
            if _bucle.fallo is not None:
                _obrero = None
                raise ErrorTrastienda(str(_bucle.fallo))

    respuesta = queue.Queue()
    _cola.put((trabajo, respuesta))
    bien, valor = respuesta.get()
    if bien:
        return valor
    raise valor


def _se_escapa(linea: str) -> bool:
    """Si eso, lanzado aquí, acabaría en el escritorio del usuario.

    `explorer.exe` no arranca nada por sí mismo: le pasa el encargo al
    explorador que ya está corriendo, y ese vive en el escritorio de siempre.
    Medido con la Calculadora el 2026-08-20: `CreateProcess` devuelve éxito, el
    `explorer.exe` hijo muere al instante, y **la ventana aparece en la pantalla
    del usuario**. Es peor que un fallo, porque nadie se entera hasta que le
    sale una ventana que no ha pedido.

    Es el camino de todas las aplicaciones de la Microsoft Store
    (`shell:AppsFolder\\…`), y por eso se rechaza antes de intentarlo.
    """
    plana = str(linea or "").casefold()
    return "explorer.exe" in plana or "shell:appsfolder" in plana


def lanzar(linea_de_comandos: str) -> int:
    """Arranca ahí dentro lo que se le diga, y devuelve el pid.

    `lpDesktop` en el `STARTUPINFO` es lo único que decide en qué escritorio
    nace el proceso, y **no se puede cambiar después**: un programa ya abierto
    se queda donde está para siempre.
    """
    if _se_escapa(linea_de_comandos):
        raise ErrorTrastienda(
            "Eso se lanza a través del explorador, que vive en el escritorio "
            "de siempre, así que la ventana **aparecería en la pantalla del "
            "usuario** en vez de aquí dentro. Le pasa a todas las aplicaciones "
            "de la Microsoft Store —WhatsApp y Spotify entre ellas—. Si tiene "
            "versión web, ábrela en un navegador de la trastienda; si no, "
            "trabájala en el escritorio de siempre y avisa de que se va a ver."
        )

    handle = abrir()
    del handle  # se abre para asegurar que existe; `lpDesktop` va por nombre

    kernel32 = ctypes.windll.kernel32
    inicio = _STARTUPINFOW()
    inicio.cb = ctypes.sizeof(inicio)
    inicio.lpDesktop = NOMBRE
    inicio.dwFlags = STARTF_USESHOWWINDOW
    inicio.wShowWindow = SW_SHOWNORMAL
    info = _PROCESS_INFORMATION()

    if not kernel32.CreateProcessW(
        None,
        ctypes.create_unicode_buffer(str(linea_de_comandos)),
        None, None, False, 0, None, None,
        ctypes.byref(inicio), ctypes.byref(info),
    ):
        codigo = kernel32.GetLastError()
        raise ErrorTrastienda(
            f"No se pudo abrir «{str(linea_de_comandos)[:60]}» en la "
            f"trastienda (error {codigo}). Las aplicaciones de la Microsoft "
            "Store no se pueden abrir aquí: se lanzan por el explorador, que "
            "vive en el escritorio de siempre."
        )
    kernel32.CloseHandle(info.hThread)
    kernel32.CloseHandle(info.hProcess)
    return int(info.dwProcessId)
