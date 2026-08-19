"""El pre-vuelo de pestañas: lo que hay que hacer antes de que Playwright mire.

Playwright se niega a conectarse a un navegador con una sola pestaña sin
renderizador —su `connectOverCDP` espera a que se inicialicen todas—, así que
antes de engancharse hay que dejarlas todas contestando. Lo que se prueba aquí
es cómo, porque lo que parece correcto no lo es: traer la pestaña al frente
devuelve un «hecho» inmediato y no la despierta.
"""
import json
import unittest
from unittest.mock import patch

from agent.vibi_node import navegador_real


class UnaPestanaFalsa:
    """El WebSocket de una pestaña, para ver qué se le manda de verdad."""

    def __init__(self, responde: bool = True):
        self.responde = responde
        self.enviado: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def send(self, crudo: str) -> None:
        self.enviado.append(json.loads(crudo))

    def recv(self, timeout: float = 0):
        if not self.responde:
            raise TimeoutError("sin renderizador detrás")
        return json.dumps({"id": 1, "result": {}})


class DetectarLaPestanaMuerta(unittest.TestCase):
    def test_se_pregunta_por_el_dominio_page(self):
        """Los de `Target` los contesta el navegador aunque no haya nadie.

        Con ellos toda pestaña parece viva y el pre-vuelo no arregla nada.
        """
        ws = UnaPestanaFalsa()
        with patch.object(navegador_real, "_conectar", return_value=lambda *a, **k: ws):
            navegador_real._contesta({"webSocketDebuggerUrl": "ws://x"})

        self.assertTrue(ws.enviado[0]["method"].startswith("Page."))

    def test_la_que_no_contesta_se_da_por_muda(self):
        ws = UnaPestanaFalsa(responde=False)
        with patch.object(navegador_real, "_conectar", return_value=lambda *a, **k: ws):
            self.assertFalse(navegador_real._contesta({"webSocketDebuggerUrl": "ws://x"}))

    def test_el_margen_del_sondeo_no_se_queda_corto(self):
        """Medido: las vivas contestan hasta en 0,97 s, y un falso positivo
        recarga una pestaña que el usuario estaba usando."""
        self.assertGreaterEqual(navegador_real.SONDEO_PESTANA, 3.0)


class DespertarlaSinTocarLaQueMira(unittest.TestCase):
    def test_se_la_navega_a_la_direccion_que_ya_tenia(self):
        """Y no a otra: es su pestaña, y tiene que quedarse donde estaba."""
        ws = UnaPestanaFalsa()
        pestana = {"webSocketDebuggerUrl": "ws://x", "url": "https://ejemplo.test/uno"}

        with patch.object(navegador_real, "_conectar", return_value=lambda *a, **k: ws), \
             patch.object(navegador_real, "_esperar_pestana", return_value=True):
            self.assertTrue(navegador_real._despertar(pestana))

        self.assertEqual(ws.enviado[0]["method"], "Page.navigate")
        self.assertEqual(ws.enviado[0]["params"]["url"], "https://ejemplo.test/uno")

    def test_no_se_traen_al_frente(self):
        """Medido: activar contesta «hecho» y la pestaña sigue muerta doce
        segundos después. Además le cambia al usuario lo que está mirando."""
        pestanas = [{"id": "a", "webSocketDebuggerUrl": "ws://a", "url": "https://a.test"}]

        with patch.object(navegador_real, "pestanas", return_value=pestanas), \
             patch.object(navegador_real, "_conectar", return_value=object()), \
             patch.object(navegador_real, "_contesta", return_value=False), \
             patch.object(navegador_real, "_despertar", return_value=True), \
             patch.object(navegador_real, "_pedir") as pedir:
            navegador_real.despertar_pestanas(9333)

        for llamada in pedir.call_args_list:
            self.assertNotIn("activate", llamada.args[1])

    def test_una_pestana_viva_no_se_toca(self):
        """Despertar es navegar, y navegar lo que el usuario está usando le
        borraría el formulario que llevara a medias."""
        pestanas = [{"id": "a", "webSocketDebuggerUrl": "ws://a", "url": "https://a.test"}]

        with patch.object(navegador_real, "pestanas", return_value=pestanas), \
             patch.object(navegador_real, "_conectar", return_value=object()), \
             patch.object(navegador_real, "_contesta", return_value=True), \
             patch.object(navegador_real, "_despertar") as despertar:
            resultado = navegador_real.despertar_pestanas(9333)

        despertar.assert_not_called()
        self.assertEqual(resultado["despertadas"], 0)
        self.assertEqual(resultado["tercas"], 0)

    def test_sin_websockets_no_se_toca_ninguna(self):
        """A ciegas todas parecen mudas, y recargarle las siete es peor que el
        fallo que se intentaba evitar."""
        pestanas = [{"id": "a", "webSocketDebuggerUrl": "ws://a", "url": "https://a.test"}]

        with patch.object(navegador_real, "pestanas", return_value=pestanas), \
             patch.object(navegador_real, "_conectar", return_value=None), \
             patch.object(navegador_real, "_despertar") as despertar:
            resultado = navegador_real.despertar_pestanas(9333)

        despertar.assert_not_called()
        self.assertTrue(resultado["omitido"])

    def test_la_que_se_resiste_se_cuenta_pero_no_corta(self):
        """Playwright fallará, pero eso lo dirá él: aquí no hay nada que hacer."""
        pestanas = [
            {"id": "a", "webSocketDebuggerUrl": "ws://a", "url": "https://a.test"},
            {"id": "b", "webSocketDebuggerUrl": "ws://b", "url": "https://b.test"},
        ]

        with patch.object(navegador_real, "pestanas", return_value=pestanas), \
             patch.object(navegador_real, "_conectar", return_value=object()), \
             patch.object(navegador_real, "_contesta", return_value=False), \
             patch.object(navegador_real, "_despertar", side_effect=[True, False]):
            resultado = navegador_real.despertar_pestanas(9333)

        self.assertEqual(resultado["revisadas"], 2)
        self.assertEqual(resultado["despertadas"], 1)
        self.assertEqual(resultado["tercas"], 1)


class ElPreVueloNoSeHacePorSiAcaso(unittest.TestCase):
    """Con el navegador ya en pie, el pre-vuelo se lo pide el enganche.

    Antes se hacía siempre, al abrir cada sesión de `agy`, y era dinero tirado
    en los dos sentidos: costaba 5 s de sondeo cuando no hacía falta —el margen
    entero se lo lleva cada pestaña dormida— y aun así no servía, porque
    Playwright no se conecta hasta la primera herramienta y para entonces las
    pestañas se habían vuelto a descartar. Ahora lo pide `browser_enganche`
    cuando la conexión falla de verdad, que es la única señal fiable.
    """

    def test_con_el_navegador_ya_en_pie_no_se_recarga_nada(self):
        with patch.object(navegador_real, "escuchando", return_value=True), \
             patch.object(navegador_real, "despertar_pestanas") as prevuelo:
            listo = navegador_real.asegurar(9333)

        prevuelo.assert_not_called()
        self.assertFalse(listo["arrancado_ahora"])
        self.assertIn("9333", listo["endpoint"])

    def test_al_abrirlo_nosotros_si_se_hace(self):
        """Ahí sí hace falta: la sesión recién restaurada deja casi todas las
        pestañas en perezoso, y el enganche fallaría entero la primera vez."""
        escuchas = iter([False, True])

        with patch.object(
            navegador_real, "escuchando", side_effect=lambda *a, **k: next(escuchas)
        ), patch.object(navegador_real, "_ejecutable", return_value="opera.exe"), \
             patch.object(navegador_real, "_corriendo", return_value=False), \
             patch.object(navegador_real, "_lanzar"), \
             patch.object(
                 navegador_real, "despertar_pestanas",
                 return_value={"revisadas": 7, "despertadas": 2, "tercas": 0},
             ) as prevuelo:
            listo = navegador_real.asegurar(9333, "opera.exe")

        prevuelo.assert_called_once()
        self.assertTrue(listo["arrancado_ahora"])


class ElNavegadorVaDeclarado(unittest.TestCase):
    def test_el_navegador_va_declarado_y_no_se_adivina(self):
        """El de por defecto de esta máquina es Zen, que es Firefox y no habla
        CDP: deducirlo daría siempre el equivocado."""
        with self.assertRaises(navegador_real.NavegadorNoEncontrado):
            navegador_real._ejecutable("")


class ElNavegadorDelUsuarioNoSeToca(unittest.TestCase):
    """Abierto a mano y sin puerto de depuracion, se deja en paz.

    Antes se le pedia el cierre y se relanzaba con el puerto, porque en caliente
    no se le puede anadir. Visto desde la silla del usuario eso es Vibi
    cerrandole el navegador que estaba usando, sin avisar y sin que hubiera
    pedido nada: se pierde el scroll, los formularios a medias y lo que
    estuviera sonando.

    El precio de no hacerlo es que Vibi no navega hasta que lo cierre el. Se
    paga a gusto: es su navegador.
    """

    def test_ni_se_relanza_ni_se_toca(self):
        with patch.object(navegador_real, "escuchando", return_value=False),              patch.object(navegador_real, "_ejecutable", return_value="opera.exe"),              patch.object(navegador_real, "_corriendo", return_value=True),              patch.object(navegador_real, "_lanzar") as lanzar:
            with self.assertRaises(navegador_real.NavegadorError):
                navegador_real.asegurar(9333, "opera.exe")

        lanzar.assert_not_called()
        self.assertFalse(hasattr(navegador_real, "_cerrar"))

    def test_el_mensaje_dice_que_hay_que_cerrarlo(self):
        """Se lo va a encontrar el usuario, asi que tiene que llevar el arreglo
        dentro: si no dice que hacer, parece que Vibi esta roto."""
        with patch.object(navegador_real, "escuchando", return_value=False),              patch.object(navegador_real, "_ejecutable", return_value="opera.exe"),              patch.object(navegador_real, "_corriendo", return_value=True),              patch.object(navegador_real, "_lanzar"):
            with self.assertRaises(navegador_real.NavegadorError) as fallo:
                navegador_real.asegurar(9333, "opera.exe")

        self.assertIn("cierralo", str(fallo.exception).lower().replace("é", "e"))

    def test_cerrado_del_todo_si_se_abre(self):
        """El caso normal no cambia: sin navegador en pie, se abre con puerto."""
        escuchas = iter([False, True])
        with patch.object(
            navegador_real, "escuchando", side_effect=lambda *a, **k: next(escuchas)
        ), patch.object(navegador_real, "_ejecutable", return_value="opera.exe"),              patch.object(navegador_real, "_corriendo", return_value=False),              patch.object(navegador_real, "_lanzar") as lanzar,              patch.object(navegador_real, "despertar_pestanas", return_value={}):
            listo = navegador_real.asegurar(9333, "opera.exe")

        lanzar.assert_called_once()
        self.assertTrue(listo["arrancado_ahora"])


if __name__ == "__main__":
    unittest.main()
