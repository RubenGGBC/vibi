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

from agent.morgana_node import navegador_real


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


class ElNavegadorSeCierraSinForzarlo(unittest.TestCase):
    def test_nunca_se_mata_a_lo_bruto(self):
        """Un cierre forzado se salta el guardado de sesión, y entonces al
        reabrir no vuelven las pestañas del usuario."""
        with patch.object(navegador_real.subprocess, "run") as correr, \
             patch.object(navegador_real, "_corriendo", return_value=False):
            navegador_real._cerrar("opera.exe", timeout=0.1)

        argv = correr.call_args.args[0]
        self.assertNotIn("/F", argv)
        self.assertNotIn("-9", argv)

    def test_el_navegador_va_declarado_y_no_se_adivina(self):
        """El de por defecto de esta máquina es Zen, que es Firefox y no habla
        CDP: deducirlo daría siempre el equivocado."""
        with self.assertRaises(navegador_real.NavegadorNoEncontrado):
            navegador_real._ejecutable("")


if __name__ == "__main__":
    unittest.main()
