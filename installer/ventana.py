"""La ventana del instalador: una aplicación de escritorio, no una pestaña.

Tiene su propio marco, su título y su tamaño, y no hay barra de direcciones ni
pestañas ni servidor web por medio. Por dentro dibuja con el WebView del
sistema —WebView2 en Windows, WebKit en macOS y Linux—, que es lo mismo que
usan casi todos los instaladores modernos y lo que permite que el halo respire
de verdad.

Se eligió así por descarte, y conviene dejarlo escrito: `tkinter` no está en
ninguna instalación de Python de esta máquina, y Qt son cien megas de descarga
antes de poder enseñar la primera pantalla.

El JS y Python se hablan directamente por el puente de pywebview. No hay
`fetch`, ni puerto, ni testigo que proteger: nada de esto sale de la máquina.
"""
from __future__ import annotations

import threading
from dataclasses import asdict

from . import acciones, agy, deteccion, pasos

# El tamaño está fijado porque el contenido lo está: seis pasos que caben
# holgados. Redimensionable solo estorbaría.
ANCHO = 780
ALTO = 780


# La ventana se guarda aquí y NO como atributo del puente, y no es un capricho:
# pywebview recorre el objeto que se le da como `js_api` para exponerlo al JS, y
# si dentro encuentra la propia ventana se mete en su árbol nativo
# (`native.AccessibilityObject.Bounds.Empty.Empty…`) hasta reventar por
# recursión. La ventana se abre y se queda sin responder.
_ventana = None


class Puente:
    """Lo que la interfaz puede pedirle a Python.

    Todo lo que aparece aquí es llamable desde el JS de la ventana, así que la
    superficie se queda en lo justo: mirar la máquina, instalar y poco más. Y
    por lo mismo no guarda nada dentro que no sea un dato simple.
    """

    def __init__(self) -> None:
        self._instalando = False

    # -- lo que se mira ------------------------------------------------

    def estado(self) -> dict:
        so = deteccion.sistema_operativo()
        requisitos = deteccion.requisitos()
        return {
            "sistema": {
                "clave": so,
                "descripcion": deteccion.descripcion_del_sistema(),
            },
            "requisitos": [asdict(r) for r in requisitos],
            "capacidades": [asdict(c) for c in deteccion.capacidades(so)],
            "se_puede": deteccion.se_puede_instalar(requisitos),
            "modelos": pasos.MODELOS,
            "ya_instalado": acciones.python_del_entorno(
                deteccion.raiz_del_repo()
            ).exists(),
        }

    # -- lo que se hace ------------------------------------------------

    def instalar(self, eleccion: dict) -> dict:
        """Arranca la instalación en su propio hilo.

        Tiene que ser en otro hilo: el que llama es el del WebView, y bloquearlo
        dejaría la ventana congelada los dos minutos que tarda todo.
        """
        if self._instalando:
            return {"ok": False, "motivo": "ya está en marcha"}
        self._instalando = True
        threading.Thread(target=self._trabajar, args=(eleccion,), daemon=True).start()
        return {"ok": True}

    def _trabajar(self, eleccion: dict) -> None:
        try:
            pasos.instalar(eleccion, self._avisar, instalador_agy=agy)
            self._avisar("listo")
        except Exception as error:  # noqa: BLE001 - el usuario tiene que verlo
            self._avisar("error", mensaje=str(error))
        finally:
            self._instalando = False

    def abrir_vibi(self) -> dict:
        """Abre la ventana de Vibi.

        Una aplicación no abre el navegador. Nunca. Si la app todavía no está
        instalada se dice, y no se disimula lanzando una pestaña en
        `127.0.0.1:8000`: eso no es Vibi, es su servidor con una ventana ajena
        delante.
        """
        if acciones.abrir_app():
            return {"ok": True}
        return {
            "ok": False,
            "motivo": (
                "Vibi funciona, pero su ventana todavía no está instalada en "
                "este ordenador."
            ),
        }

    def _avisar(self, tipo: str, **datos) -> None:
        """Empuja un evento a la interfaz.

        Va de Python al JS y no al revés —nada de sondear— para que cada línea
        de `pip` aparezca en cuanto se genera.
        """
        if _ventana is None:
            return
        import json  # noqa: PLC0415

        carga = json.dumps({"tipo": tipo, **datos}, ensure_ascii=False)
        try:
            _ventana.evaluate_js(f"window.recibirEvento({carga})")
        except Exception:  # noqa: BLE001 - la ventana pudo cerrarse a mitad
            pass


def abrir() -> None:
    """Abre la ventana y no vuelve hasta que se cierra."""
    import webview  # noqa: PLC0415 - vive en el entorno, no en el Python base

    global _ventana

    puente = Puente()
    ui = deteccion.raiz_del_repo() / "installer" / "ui" / "index.html"
    _ventana = webview.create_window(
        "Vibi",
        str(ui),
        js_api=puente,
        width=ANCHO,
        height=ALTO,
        resizable=False,
        # El fondo se pinta antes de que cargue el HTML: sin esto, la ventana
        # parpadea en blanco al abrirse y rompe la entrada de golpe.
        background_color="#0b0810",
    )
    webview.start()
