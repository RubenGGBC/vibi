"""Deja el navegador del usuario en pie y con CDP listo.

Vibi navegaba en un Chrome recién estrenado, con un perfil propio que no
había iniciado sesión en nada: cada vez que había que entrar en un sitio se
quedaba en la puerta. Este módulo es lo que hace posible lo contrario —abrir una
pestaña en el navegador del usuario, con su usuario— y su único trabajo es ese:
garantizar que hay un navegador escuchando CDP y decir dónde. No sabe nada de
MCP ni de Playwright; quien se engancha al endpoint es `browser_mcp`.

El perfil aparte no fue capricho: Chromium no deja dos instancias sobre el mismo
directorio de perfil, así que compartirlo significaba no poder navegar mientras
Vibi navega. La salida no es compartir el perfil sino no lanzar navegador
ninguno: se engancha al que ya está abierto por el puerto de depuración.

Dos cosas medidas que explican por qué el módulo hace lo que hace:

- **Opera GX 133 es Chromium 149 y aun así abre el puerto de depuración sobre el
  perfil por defecto.** Chromium lo bloquea desde la 136; Opera no aplica la
  restricción. Toda esta vía cuelga de ahí, y con Chrome o Edge no funcionaría.
- **Una sola pestaña sin renderizador cuelga la conexión entera 30 s.**
  Playwright cierra su `CRBrowser.connect` con un
  `_waitForAllPagesToBeInitialized()` que no admite excepciones, así que una
  pestaña que no conteste a CDP —restaurada y todavía sin cargar— deja a Vibi
  sin navegador con un error que no señala a ninguna parte. De ahí el pre-vuelo.
- **A una pestaña así no se la despierta trayéndola al frente.** Ni
  `/json/activate` ni `Target.activateTarget`: las dos contestan «hecho» al
  instante y la pestaña sigue sin renderizador doce segundos después. Lo que la
  despierta —en 0,1 s— es navegarla a la dirección que ya tenía. Importa porque
  activar es lo que parece correcto, tiene buena pinta al leerlo y no funciona.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import proceso

PUERTO_POR_DEFECTO = 9333

# Abrir un navegador con la sesión entera del usuario no es instantáneo, pero
# tampoco es una descarga: si en medio minuto no ha abierto el puerto, algo va
# mal y es mejor decirlo que seguir esperando.
ARRANQUE_TIMEOUT = 45.0
SONDEO = 0.25

# Lo que se le da a un navegador para que se cierre él solo, guardando su
# sesión. Nunca se fuerza: un cierre forzado se salta el guardado y entonces
# reabrir no devuelve las pestañas.
#
# Generoso a propósito. Un Chromium con diez pestañas y vídeo tarda en bajar
# todos sus procesos hijo, y medido aquí pasa de los quince segundos. Quedarse
# corto no acelera nada: solo hace que se dé por fallido un cierre que iba bien.
CIERRE_TIMEOUT = 60.0

# Cuánto se espera a que una pestaña conteste antes de darla por dormida.
# Medido en este equipo con siete pestañas: las vivas contestan entre 0,01 s y
# 0,97 s. El margen es grande a propósito porque los dos errores no cuestan lo
# mismo: dar por dormida una viva la recarga —y se lleva por delante lo que
# hubiera escrito en un formulario—, mientras que dar por viva una dormida solo
# cuesta el intento siguiente.
SONDEO_PESTANA = 5.0

# Cuánto se espera a que una pestaña recién navegada conteste. Medido: 0,1 s
# por la conexión de la pestaña y 0,3 s por la del navegador. El margen es para
# una máquina cargada; llegar aquí ya significa que la pestaña estaba muerta.
CARGA_PESTANA = 8.0

# Techo del pre-vuelo entero. Sobra con el sondeo y el despertar en paralelo,
# pero sigue estando: el usuario está esperando su respuesta al otro lado.
PREVUELO_TIMEOUT = 20.0

# Cuántas pestañas se sondean a la vez. El sondeo es espera de red, no cálculo,
# así que el límite no es la CPU sino no abrirle al navegador treinta
# WebSockets de golpe.
SONDEOS_A_LA_VEZ = 8


class NavegadorError(Exception):
    pass


class NavegadorNoEncontrado(NavegadorError):
    pass


def _pedir(puerto: int, ruta: str, timeout: float = 2.0):
    """Una llamada al endpoint HTTP de DevTools, o None si no contesta.

    Se habla por `127.0.0.1` y no por `localhost` a propósito: DevTools mira el
    `Host` que le llega y rechaza los nombres que no reconoce, igual que hace
    Playwright con el suyo.
    """
    url = f"http://127.0.0.1:{puerto}{ruta}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as respuesta:  # noqa: S310
            return json.loads(respuesta.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError):
        return None


def escuchando(puerto: int, timeout: float = 2.0) -> bool:
    """¿Hay un navegador con CDP en ese puerto?

    Se pregunta por HTTP y no por TCP —al revés que en `browser_mcp`— porque
    aquí sí importa *qué* hay detrás: un puerto ocupado por otra cosa no sirve,
    y responder a `/json/version` es lo que distingue un navegador de un vecino.
    """
    return _pedir(puerto, "/json/version", timeout) is not None


def pestanas(puerto: int) -> list[dict]:
    """Las pestañas de verdad, sin los service workers ni las páginas internas."""
    objetivos = _pedir(puerto, "/json/list", timeout=5.0) or []
    return [t for t in objetivos if t.get("type") == "page"]


def _conectar():
    """El cliente WebSocket síncrono, o None si no está instalado.

    Se pregunta antes de sondear y no dentro de cada sondeo, porque sin él
    *ninguna* pestaña contestaría y darlas todas por dormidas acabaría
    recargándole al usuario las que tiene abiertas. Cuando falta, el pre-vuelo
    se salta entero: es una dependencia declarada, y si no está, el fallo es de
    la instalación y no del navegador.
    """
    try:
        from websockets.sync.client import connect  # noqa: PLC0415 - opcional
    except ImportError:
        return None
    return connect


def _contesta(pestana: dict) -> bool:
    """¿Tiene esta pestaña un renderizador vivo detrás?

    Se le manda `Page.getFrameTree`, que es de solo lectura y no cambia nada de
    lo que el usuario tenga delante. Una pestaña cargada responde en
    milisegundos; una restaurada y todavía sin cargar no responde nunca, y es
    exactamente la que cuelga a Playwright.

    Tiene que ser un comando del dominio `Page`, que lo atiende el renderizador.
    Los de `Target` los responde el proceso del navegador y contestan al
    instante aunque la pestaña esté vacía por dentro: con ellos toda pestaña
    parece viva y el pre-vuelo no encuentra nada que arreglar.
    """
    conectar = _conectar()
    url = pestana.get("webSocketDebuggerUrl")
    if conectar is None or not url:
        return False

    try:
        with conectar(url, open_timeout=SONDEO_PESTANA, close_timeout=1) as ws:
            ws.send(json.dumps({"id": 1, "method": "Page.getFrameTree"}))
            ws.recv(timeout=SONDEO_PESTANA)
        return True
    except Exception:  # noqa: BLE001 - cualquier fallo aquí significa «dormida»
        return False


def _despertar(pestana: dict, margen: float = CARGA_PESTANA) -> bool:
    """Le crea el renderizador navegándola a la dirección que ya tenía.

    Es lo único que funciona, y no es lo que parecía. Traerla al frente
    —`/json/activate` por HTTP o `Target.activateTarget` por CDP— devuelve un
    «hecho» inmediato y **no la despierta**: medido aquí, doce segundos en
    primer plano y sigue sin renderizador. Navegarla a su propia URL la deja
    contestando en 0,1 s, y además sin tocar qué pestaña está mirando el
    usuario, que era el precio del otro camino.

    Recargar no le quita nada: una pestaña descartada no tiene estado en
    memoria que perder, y esto es exactamente lo que le pasaría al pincharla.
    Por eso importa no equivocarse al sondear, y de ahí el margen de
    `SONDEO_PESTANA`.

    `margen` acota la espera. Sin él, con las pestañas suficientes esto se
    llevaba por delante el presupuesto entero de quien llama: la orden de nodo
    se daba por perdida y el usuario se quedaba sin navegador. Cortar aquí no
    cuesta casi nada, porque la navegación ya está pedida y la pestaña termina
    de despertarse igual aunque nosotros dejemos de mirar.
    """
    conectar = _conectar()
    url = pestana.get("webSocketDebuggerUrl")
    destino = pestana.get("url") or ""
    if conectar is None or not url or not destino:
        return False

    espera = max(0.5, min(margen, CARGA_PESTANA))
    try:
        with conectar(url, open_timeout=min(SONDEO_PESTANA, espera), close_timeout=1) as ws:
            ws.send(
                json.dumps(
                    {"id": 1, "method": "Page.navigate", "params": {"url": destino}}
                )
            )
            ws.recv(timeout=espera)
    except Exception:  # noqa: BLE001 - la terca se cuenta, no se denuncia
        return False
    return _esperar_pestana(pestana, espera)


def despertar_pestanas(puerto: int, presupuesto: float = PREVUELO_TIMEOUT) -> dict:
    """Carga las pestañas que no contestan, sin cambiar la que el usuario mira.

    Sin esto, la conexión de Playwright se queda colgada 30 s y muere sin decir
    qué pestaña tuvo la culpa: su `connectOverCDP` espera a que se inicialicen
    todas y no admite excepciones, así que una sola pestaña muerta deja a
    Vibi sin navegador.

    Se sondea antes de tocar nada porque despertar es navegar, y navegar una
    pestaña viva le recargaría al usuario algo que estaba usando. Lo normal es
    que estén mudas las que acaba de restaurar la sesión y ninguna más: aquí,
    dos de siete.

    En paralelo las dos fases, y no por prisa gratuita: lo que se está haciendo
    es esperar a la red, el usuario tiene la pregunta a medias al otro lado, y
    en serie el sondeo solo ya costaba siete segundos porque las mudas se
    llevan el timeout entero cada una.
    """
    conectar = _conectar()
    abiertas = pestanas(puerto)
    if not abiertas or conectar is None:
        # Sin `websockets` no se puede distinguir una pestaña muda de una viva,
        # y a ciegas lo único seguro es no tocar ninguna: recargarle las siete
        # es peor que el fallo que se intentaba evitar.
        return {
            "revisadas": len(abiertas),
            "despertadas": 0,
            "tercas": 0,
            "omitido": conectar is None,
        }

    limite = time.time() + presupuesto
    with ThreadPoolExecutor(max_workers=SONDEOS_A_LA_VEZ) as hilos:
        mudas = [
            pestana
            for pestana, viva in zip(abiertas, hilos.map(_contesta, abiertas))
            if not viva
        ]
        if not mudas:
            return {"revisadas": len(abiertas), "despertadas": 0, "tercas": 0}
        restante = limite - time.time()
        if restante <= 0:
            # Se acabó el presupuesto sondeando. Seguir costaría más de lo que
            # cuesta el fallo que se intenta evitar, y con el usuario esperando.
            return {
                "revisadas": len(abiertas),
                "despertadas": 0,
                "tercas": len(mudas),
            }
        # Lo que quede se reparte entre las tandas que hagan falta: con más
        # mudas que hilos van por turnos, y sin repartir la última tanda se
        # comería el presupuesto de quien llama. Es lo que tumbó una orden de
        # nodo entera el 16/08/2026.
        tandas = max(1, -(-len(mudas) // SONDEOS_A_LA_VEZ))
        margen = restante / tandas
        despertadas = sum(hilos.map(lambda p: _despertar(p, margen), mudas))

    return {
        "revisadas": len(abiertas),
        "despertadas": despertadas,
        "tercas": len(mudas) - despertadas,
    }


def _esperar_pestana(pestana: dict, timeout: float) -> bool:
    """Espera a que una pestaña recién traída al frente termine de cargar."""
    limite = time.time() + max(timeout, 0.0)
    while time.time() < limite:
        if _contesta(pestana):
            return True
        time.sleep(SONDEO)
    return False


def _ejecutable(declarado: str) -> str:
    """Dónde está el navegador que se va a pilotar.

    Va declarado y no se autodetecta del sistema: el navegador por defecto del
    usuario puede ser un Firefox —Zen lo es—, y Firefox no habla CDP. Deducirlo
    daría siempre el navegador equivocado.
    """
    ruta = (declarado or "").strip()
    if not ruta:
        raise NavegadorNoEncontrado(
            "No sé qué navegador abrir: declara PLAYWRIGHT_MCP_BROWSER_PATH con "
            "la ruta de un navegador basado en Chromium (Opera, Chrome, Edge)."
        )
    if not Path(ruta).exists():
        vecino = shutil.which(ruta)
        if vecino is None:
            raise NavegadorNoEncontrado(f"No existe el navegador: {ruta}")
        return vecino
    return ruta


def _corriendo(ejecutable: str) -> bool:
    """¿Está ya abierto ese navegador, aunque sea sin puerto de depuración?"""
    nombre = Path(ejecutable).name
    try:
        if sys.platform == "win32":
            salida = subprocess.run(  # noqa: S603 - argv es nuestro
                ["tasklist", "/FI", f"IMAGENAME eq {nombre}", "/NH"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
            return nombre.lower() in salida.lower()
        return (
            subprocess.run(  # noqa: S603 - argv es nuestro
                ["pgrep", "-f", nombre],
                capture_output=True,
                timeout=15,
                **proceso.sin_ventana(),
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        # Si no se puede averiguar, se dice que no: el peor caso es intentar
        # lanzarlo y que Chromium reenvíe la orden a la instancia que ya había,
        # que se detecta después porque el puerto no llega a abrirse.
        return False


def _cerrar(ejecutable: str, timeout: float = CIERRE_TIMEOUT) -> bool:
    """Pide al navegador que se cierre, sin forzarlo nunca.

    Un navegador que el usuario abrió por su cuenta no tiene puerto de
    depuración, y no hay forma de añadírselo en caliente: hay que reabrirlo. Se
    le pide el cierre y se le deja guardar la sesión, que es lo que después la
    restaura con todas las pestañas.

    Nunca `/F` ni `SIGKILL`. Un cierre forzado se salta el guardado de sesión, y
    entonces reabrir no devuelve nada.
    """
    nombre = Path(ejecutable).name
    try:
        if sys.platform == "win32":
            # Sin `/F`: `taskkill` manda WM_CLOSE a las ventanas, que es lo
            # mismo que pulsar la equis.
            subprocess.run(  # noqa: S603 - argv es nuestro
                ["taskkill", "/IM", nombre],
                capture_output=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.run(  # noqa: S603 - argv es nuestro
                ["pkill", "-TERM", "-f", nombre],
                capture_output=True,
                timeout=15,
                **proceso.sin_ventana(),
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise NavegadorError(f"No pude pedirle a {nombre} que se cerrara: {error}")

    limite = time.time() + timeout
    while time.time() < limite:
        if not _corriendo(ejecutable):
            return True
        time.sleep(SONDEO)
    return False


def _lanzar(ejecutable: str, puerto: int) -> None:
    """Abre el navegador con el puerto de depuración, desligado de este proceso.

    Sin `--user-data-dir`: usar el perfil por defecto es justamente el sentido
    de todo esto, y nombrarlo aquí no cambiaría nada salvo el riesgo de escribir
    mal la ruta.

    Y sin `--remote-allow-origins=*`. Chromium rechaza por defecto los
    WebSocket de CDP que llegan con un `Origin` de página, y ese rechazo es lo
    único que impide que una web que estés visitando se ponga a pilotar tu
    navegador con tus sesiones abiertas. El comodín lo apaga para todos. Como
    Playwright conecta desde Node y no manda `Origin`, no hace falta.
    """
    argv = [ejecutable, f"--remote-debugging-port={puerto}"]
    opciones: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                      "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        opciones["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        opciones["start_new_session"] = True
    try:
        subprocess.Popen(argv, **opciones)  # noqa: S603 - argv es nuestro
    except OSError as error:
        raise NavegadorError(f"No se pudo abrir el navegador: {error}") from error


def asegurar(
    puerto: int = PUERTO_POR_DEFECTO,
    ejecutable: str = "",
    timeout: float = ARRANQUE_TIMEOUT,
) -> dict:
    """Deja el navegador del usuario listo para que Playwright se enganche.

    Es idempotente y barato cuando ya está todo en pie, que es el caso normal:
    Vibi llama a esto al abrir cada sesión de `agy`.

    Con el navegador ya abierto no se hace pre-vuelo, y es un cambio a peor solo
    en apariencia. Hacerlo aquí costaba los 5 s del sondeo en cada sesión —una
    pestaña dormida se lleva el margen entero— y no arreglaba el fallo que
    pretendía evitar: Playwright no se conecta al arrancar el servidor sino en
    la primera herramienta que use el modelo, y de aquí a allí el navegador
    vuelve a descartar pestañas. Quien lo pide ahora es `browser_enganche`,
    cuando la conexión falla de verdad, que es la única señal que no miente.
    """
    if escuchando(puerto):
        return {
            "endpoint": f"http://127.0.0.1:{puerto}",
            "arrancado_ahora": False,
            "reabierto": False,
            "pestanas": {},
        }

    ruta = _ejecutable(ejecutable)

    # Abierto pero sin puerto: es el navegador que el usuario abrió él. El
    # puerto no se puede añadir en caliente, así que hay que reabrirlo. Se le
    # deja guardar la sesión para que al volver estén sus pestañas.
    #
    # Si no termina de cerrarse a tiempo se lanza igual, y a propósito. Rendirse
    # aquí dejaría al usuario con el navegador cerrado por nuestra culpa y sin
    # nada a cambio, que es el peor final posible de los tres. Lanzar de más no
    # duele: si la instancia anterior sigue viva, Chromium le reenvía la orden y
    # el proceso nuevo se va solo; eso se nota luego, porque el puerto no llega
    # a abrirse, y entonces sí hay un mensaje que decir.
    reabierto = False
    if _corriendo(ruta):
        _cerrar(ruta)
        reabierto = True

    _lanzar(ruta, puerto)

    limite = time.time() + timeout
    while time.time() < limite:
        if escuchando(puerto, timeout=1.0):
            return {
                "endpoint": f"http://127.0.0.1:{puerto}",
                "arrancado_ahora": True,
                "reabierto": reabierto,
                "pestanas": despertar_pestanas(puerto),
            }
        time.sleep(SONDEO)

    raise NavegadorError(
        f"{Path(ruta).name} no abrió el puerto de depuración {puerto} en "
        f"{timeout:.0f}s. Si ya lo tenías abierto, ciérralo del todo y "
        "reinténtalo."
    )


def estado(puerto: int = PUERTO_POR_DEFECTO) -> dict:
    version = _pedir(puerto, "/json/version") or {}
    return {
        "puerto": puerto,
        "escuchando": bool(version),
        "navegador": version.get("Browser", ""),
        "pestanas": len(pestanas(puerto)) if version else 0,
    }
