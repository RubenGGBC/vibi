"""Inventario local y lanzamiento tipado de aplicaciones Windows.

El servidor solo manda un nombre o un identificador opaco. Los objetivos de
lanzamiento nacen y se quedan en el agente: ninguna ruta ejecutable cruza el
WebSocket y ningún texto del usuario se convierte en una línea de comandos.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import proceso

log = logging.getLogger("vibi.node.apps")

MAX_CANDIDATES = 5
REFRESH_COOLDOWN = 300.0
PERIODIC_REFRESH_SECONDS = 6 * 60 * 60
_ARTICLES = frozenset({"el", "la", "los", "las", "un", "una", "unos", "unas"})
_UNSAFE_CHARS = re.compile(r"[\\/;&|<>`$\"']")
_COMMAND_FLAG = re.compile(r"(?:^|\s)--?[\w]")
_FILE_SUFFIX = re.compile(
    r"\.(?:exe|com|bat|cmd|ps1|msi|pdf|docx?|xlsx?|pptx?|txt|zip|rar)$",
    re.IGNORECASE,
)
_PACKAGED_COMMAND = (
    "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
)


@dataclass(frozen=True, slots=True)
class AppEntry:
    id: str
    label: str
    aliases: tuple[str, ...]
    launch_kind: str
    target: str


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    ready: bool = False
    entries: tuple[AppEntry, ...] = ()
    refreshed_at: float = 0.0
    error: str = ""


def normalize_alias(value: object) -> str:
    """Normaliza para comparar, sin producir nunca un objetivo ejecutable."""
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    words = re.sub(r"[^a-z0-9]+", " ", without_accents).split()
    if words and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words)


def _safe_query(value: object) -> str:
    query = str(value or "").strip()
    if not query or len(query) > 200:
        return ""
    if "://" in query or _UNSAFE_CHARS.search(query):
        return ""
    if _COMMAND_FLAG.search(query) or _FILE_SUFFIX.search(query):
        return ""
    return query


def _public(entry: AppEntry) -> dict[str, str]:
    return {"id": entry.id, "label": entry.label}


class ApplicationCatalog:
    """Snapshot inmutable que se refresca sin bloquear sus lectores."""

    def __init__(
        self,
        discover: Callable[[], Iterable[AppEntry]],
        launcher: Callable[[AppEntry], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        refresh_interval: float = PERIODIC_REFRESH_SECONDS,
    ) -> None:
        self._discover = discover
        self._launcher = launcher
        self._clock = clock
        self._refresh_interval = refresh_interval
        self._snapshot = CatalogSnapshot()
        self._refresh_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False

    @property
    def snapshot(self) -> CatalogSnapshot:
        return self._snapshot

    def start_background(self) -> None:
        """Inicia el primer inventario una vez y vuelve inmediatamente."""
        with self._start_lock:
            if self._started:
                return
            self._started = True
        threading.Thread(
            target=self._refresh_loop,
            name="vibi-app-catalog",
            daemon=True,
        ).start()

    def _refresh_loop(self) -> None:
        self.refresh()
        while not self._stop.wait(self._refresh_interval):
            self.refresh()

    def stop_background(self) -> None:
        """Detiene el refresco periódico (principalmente para apagado y tests)."""
        self._stop.set()

    def refresh(self) -> None:
        """Construye fuera del estado visible y sustituye la foto al acabar."""
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            error = ""
            try:
                discovered = tuple(self._discover())
                unique = {entry.id: entry for entry in discovered}
                entries = tuple(
                    sorted(unique.values(), key=lambda item: item.label.casefold())
                )
            except Exception as exc:  # noqa: BLE001 - el agente debe seguir vivo
                entries = ()
                error = str(exc)[:300]
                log.warning("No se pudo construir el catálogo de aplicaciones: %s", exc)
            self._snapshot = CatalogSnapshot(
                ready=True,
                entries=entries,
                refreshed_at=self._clock(),
                error=error,
            )
            log.info("Catálogo de aplicaciones listo: %s entradas", len(entries))
        finally:
            self._refresh_lock.release()

    def _refresh_after_miss(self) -> None:
        snapshot = self._snapshot
        if self._clock() - snapshot.refreshed_at < REFRESH_COOLDOWN:
            return
        threading.Thread(
            target=self.refresh,
            name="vibi-app-catalog-refresh",
            daemon=True,
        ).start()

    def resolver(self, query: object) -> AppEntry | None:
        """La aplicación que se llama así, o `None` si no hay una sola.

        Es la mitad de `launch` que no lanza nada, separada para que la
        trastienda pueda resolver el mismo nombre y abrirlo por otro camino.
        Devuelve `None` tanto si no hay ninguna como si hay varias: elegir por
        el usuario entre dos aplicaciones parecidas es como se acaba abriendo
        la que no era.
        """
        candidatas = self._candidatas(query)
        return candidatas[0] if len(candidatas) == 1 else None

    def _candidatas(self, query: object) -> list[AppEntry]:
        snapshot = self._snapshot
        if not snapshot.ready:
            return []
        safe = _safe_query(query)
        if not safe:
            return []
        by_id = [entry for entry in snapshot.entries if entry.id == safe]
        normalized = normalize_alias(safe)
        exact_by_id = {
            entry.id: entry
            for entry in snapshot.entries
            if normalized and normalized in entry.aliases
        }
        return _sin_repetidas(by_id or list(exact_by_id.values()))

    def launch(self, query: object) -> dict:
        started = self._clock()
        snapshot = self._snapshot
        if not snapshot.ready:
            return {"status": "catalog_starting", "node_execution_ms": 0}

        safe = _safe_query(query)
        if not safe:
            return {"status": "not_found", "candidates": [], "node_execution_ms": 0}

        normalized = normalize_alias(safe)
        matches = self._candidatas(query)
        if len(matches) > 1:
            return {
                "status": "ambiguous",
                "candidates": [_public(entry) for entry in matches[:MAX_CANDIDATES]],
                "node_execution_ms": round((self._clock() - started) * 1000),
            }
        if len(matches) == 1:
            entry = matches[0]
            # Si es de las que son Chromium por dentro, se abre escuchando: así
            # después se puede manejar por su DOM, sin ponerla delante ni
            # tocarle el ratón a nadie. Cuesta un argumento y no cambia nada
            # de cómo se ve la aplicación. Ver `web_apps`.
            extra: tuple[str, ...] = ()
            puerto = 0
            try:
                from . import web_apps

                if entry.launch_kind != "packaged" and web_apps.es_chromium(
                    entry.label
                ):
                    puerto = web_apps.reservar(entry.label)
                    extra = (web_apps.flag_de_depuracion(puerto),)
            except Exception:
                extra, puerto = (), 0
            try:
                self._launcher(entry, extra) if extra else self._launcher(entry)
            except Exception as exc:  # noqa: BLE001 - se devuelve como resultado tipado
                if puerto:
                    from . import web_apps

                    web_apps.olvidar(entry.label)
                return {
                    "status": "launch_failed",
                    "app": _public(entry),
                    "error": str(exc)[:300],
                    "node_execution_ms": round((self._clock() - started) * 1000),
                }
            return {
                "status": "launched",
                "app": _public(entry),
                **({"puerto_web": puerto} if puerto else {}),
                "node_execution_ms": round((self._clock() - started) * 1000),
            }

        partial = [
            entry
            for entry in snapshot.entries
            if normalized
            and any(normalized in alias or alias in normalized for alias in entry.aliases)
        ]
        self._refresh_after_miss()
        return {
            "status": "not_found",
            "candidates": [_public(entry) for entry in partial[:MAX_CANDIDATES]],
            "node_execution_ms": round((self._clock() - started) * 1000),
        }


def _a_donde_lleva(entrada: AppEntry) -> str:
    """El programa al que apunta esa entrada, resuelto y en minúsculas.

    Un acceso directo se resuelve a su ejecutable; lo demás vale tal cual. Se
    normaliza porque el mismo programa aparece escrito de formas distintas
    según de dónde salga la entrada: `C:\\Users\\x\\...\\Update.exe` y
    `C:\\Users\\X\\...\\update.EXE` son el mismo archivo.
    """
    destino = destino_real(entrada.target)
    ruta = destino[0] if destino else entrada.target
    return " ".join(str(ruta or "").casefold().split())


def _sin_repetidas(entradas: list[AppEntry]) -> list[AppEntry]:
    """Quita las entradas que llevan al mismo programa.

    Medido el 2026-08-20: **Discord salía tres veces** en este equipo —dos
    accesos directos, del menú de inicio del usuario y del de todos, más su
    entrada empaquetada—, y los tres abrían lo mismo. Con eso,
    `launch("Discord")` contestaba «ambiguo» y no abría nada: le pedía a quien
    preguntara que eligiera entre tres cosas idénticas.

    Dos entradas que llevan al mismo sitio no son una elección. Dos que llevan
    a sitios distintos sí, y ésas se dejan: en esta máquina hay dos «chrome»
    de verdad —Google Chrome y Helium—, y ahí preguntar es lo correcto.

    Se prefiere el acceso directo al paquete: un `.lnk` se puede resolver a su
    ejecutable y por tanto admite argumentos, y una entrada empaquetada no
    —de eso depende que la aplicación pueda abrirse escuchando, o entrar en la
    trastienda—.
    """
    salida: list[AppEntry] = []
    for entrada in entradas:
        gemela = next(
            (
                i
                for i, ya in enumerate(salida)
                if _es_la_misma_app(ya, entrada)
            ),
            None,
        )
        if gemela is None:
            salida.append(entrada)
        elif _mejor_que(entrada, salida[gemela]):
            salida[gemela] = entrada
    return salida


def _es_la_misma_app(una: AppEntry, otra: AppEntry) -> bool:
    """Si dos entradas abren el mismo programa.

    Tres formas de serlo, y las tres salieron de mirar este equipo:

    1. **Llevan al mismo archivo.** El mismo `.lnk` duplicado en el menú de
       inicio del usuario y en el de todos.
    2. **Una es el paquete de la otra.** Discord y Opera aparecen como acceso
       directo *y* como aplicación empaquetada; es la misma, anunciada dos
       veces.
    3. **Cuelgan de la misma carpeta de instalación.** Discord tiene un acceso
       a `…\\Discord\\app-1.0.9254\\Discord.exe` y otro a
       `…\\Discord\\Update.exe`, que es su lanzador. Distinto archivo, misma
       aplicación.

    Lo que **no** es lo mismo: dos programas con el mismo nombre en sitios sin
    relación. En esta máquina hay dos «chrome» —Google Chrome en *Program
    Files* y Helium en *AppData*— y ésos sí son una elección de verdad.
    """
    if normalize_alias(una.label) != normalize_alias(otra.label):
        return False
    ruta_una, ruta_otra = _a_donde_lleva(una), _a_donde_lleva(otra)
    if ruta_una and ruta_una == ruta_otra:
        return True
    if (una.launch_kind == "packaged") != (otra.launch_kind == "packaged"):
        return True
    carpeta_una = ruta_una.rsplit("\\", 1)[0] if "\\" in ruta_una else ruta_una
    carpeta_otra = (
        ruta_otra.rsplit("\\", 1)[0] if "\\" in ruta_otra else ruta_otra
    )
    if not carpeta_una or not carpeta_otra:
        return False
    return carpeta_una.startswith(carpeta_otra) or carpeta_otra.startswith(
        carpeta_una
    )


# Cuál se queda cuando dos entradas son la misma aplicación. Se prefiere lo que
# se puede lanzar con argumentos: de eso depende que la aplicación pueda abrirse
# escuchando por su puerto de depuración, o entrar en la trastienda. Una entrada
# empaquetada no admite ninguno.
ORDEN_DE_PREFERENCIA = {"shortcut": 0, "app_path": 1, "packaged": 2}


def _mejor_que(candidata: AppEntry, actual: AppEntry) -> bool:
    return ORDEN_DE_PREFERENCIA.get(
        candidata.launch_kind, 9
    ) < ORDEN_DE_PREFERENCIA.get(actual.launch_kind, 9)


def _entry(kind: str, label: object, target: object) -> AppEntry | None:
    clean_label = str(label or "").strip()
    clean_target = str(target or "").strip()
    alias = normalize_alias(clean_label)
    if not clean_label or not clean_target or not alias:
        return None
    digest = hashlib.blake2s(
        f"{kind}\0{clean_target.casefold()}".encode("utf-8"), digest_size=10
    ).hexdigest()
    return AppEntry(
        id=f"app_{digest}",
        label=clean_label[:160],
        aliases=(alias,),
        launch_kind=kind,
        target=clean_target,
    )


def _start_menu_entries() -> Iterable[AppEntry]:
    roots = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if programdata:
        roots.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    for root in roots:
        try:
            shortcuts = root.rglob("*.lnk") if root.is_dir() else ()
            for shortcut in shortcuts:
                found = _entry("shortcut", shortcut.stem, shortcut)
                if found is not None:
                    yield found
        except OSError as exc:
            log.debug("No se pudo recorrer %s: %s", root, exc)


def _app_path_entries() -> Iterable[AppEntry]:
    try:
        import winreg  # noqa: PLC0415 - solo existe en Windows
    except ImportError:
        return

    registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    views = [0]
    for attribute in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        value = getattr(winreg, attribute, 0)
        if value and value not in views:
            views.append(value)
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in views:
            try:
                root = winreg.OpenKey(hive, registry_path, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with root:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, name) as key:
                            target = str(winreg.QueryValueEx(key, "")[0]).strip()
                    except OSError:
                        continue
                    if target.startswith('"') and target.endswith('"'):
                        target = target[1:-1]
                    if not target.casefold().endswith(".exe"):
                        continue
                    found = _entry("app_path", Path(name).stem, target)
                    if found is not None:
                        yield found


def _packaged_entries() -> Iterable[AppEntry]:
    executable = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not executable:
        return
    try:
        completed = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", _PACKAGED_COMMAND],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            **proceso.sin_ventana(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("No se pudieron enumerar apps empaquetadas: %s", exc)
        return
    if completed.returncode != 0 or not completed.stdout.strip():
        return
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return
    rows = payload if isinstance(payload, list) else [payload]
    for row in rows:
        if not isinstance(row, dict):
            continue
        found = _entry("packaged", row.get("Name"), row.get("AppID"))
        if found is not None:
            yield found


def discover_windows_apps() -> tuple[AppEntry, ...]:
    if sys.platform != "win32":
        return ()
    return tuple((*_start_menu_entries(), *_app_path_entries(), *_packaged_entries()))


def destino_real(ruta: str) -> tuple[str, str] | None:
    """A qué apunta un acceso directo: `(ejecutable, argumentos)`.

    Hace falta para poder añadirle un argumento al arrancar, que es lo que
    `os.startfile` no deja hacer. Se resuelve con el objeto COM del shell, el
    mismo que usa el explorador; devolver `None` cuando no se puede es
    deliberado, porque entonces se abre como siempre y no pasa nada grave.
    """
    if not str(ruta).lower().endswith(".lnk"):
        return None
    try:
        import comtypes.client as cliente

        # **`dynamic=True` no es opcional.** Sin él, `comtypes` devuelve un
        # `IDispatch` pelado y `acceso.TargetPath` levanta `AttributeError`:
        # las propiedades de un objeto de automatización solo existen si se
        # resuelven en tiempo de ejecución. El síntoma es silencioso —esta
        # función devolvía `None` siempre— y con él se caían dos cosas: abrir
        # una app con el flag de depuración, y distinguir dos accesos directos
        # que llevan al mismo programa.
        shell = cliente.CreateObject("WScript.Shell", dynamic=True)
        acceso = shell.CreateShortcut(str(ruta))
        objetivo = str(acceso.TargetPath or "").strip()
        if not objetivo:
            return None
        return objetivo, str(acceso.Arguments or "").strip()
    except Exception:
        return None


def launch_windows_entry(entry: AppEntry, argumentos: tuple[str, ...] = ()) -> None:
    """Abre esa aplicación, opcionalmente con argumentos extra.

    Los argumentos son la vía para que una aplicación de Chromium arranque
    escuchando y se pueda manejar por dentro sin robarle la pantalla a nadie
    (ver `web_apps`). Y solo se pueden pasar arrancando el ejecutable
    directamente: ni `os.startfile` ni el shell de las apps empaquetadas
    admiten nada más que la ruta.
    """
    if entry.launch_kind in {"shortcut", "app_path"}:
        if argumentos:
            objetivo = entry.target
            extra: list[str] = []
            resuelto = destino_real(entry.target)
            if resuelto is not None:
                objetivo, propios = resuelto
                extra = propios.split() if propios else []
            if objetivo.lower().endswith(".exe"):
                subprocess.Popen(
                    [objetivo, *extra, *argumentos],
                    close_fds=True,
                    **proceso.sin_ventana(),
                )
                return
            # No se pudo resolver a un ejecutable: se abre normal. Perder el
            # argumento es mucho mejor que no abrir la aplicación.
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise OSError("Este sistema no ofrece os.startfile")
        startfile(entry.target)
        return
    if entry.launch_kind == "packaged":
        # Las de la Store se lanzan por el shell y **no admiten argumentos**:
        # WhatsApp y Spotify son de estas, así que a ellas no se les puede
        # abrir el puerto por aquí. Se abren igual, sin él.
        subprocess.Popen(
            ["explorer.exe", f"shell:AppsFolder\\{entry.target}"],
            close_fds=True,
            **proceso.sin_ventana(),
        )
        return
    raise OSError(f"Tipo de aplicación no soportado: {entry.launch_kind}")


catalog = ApplicationCatalog(discover_windows_apps, launch_windows_entry)
