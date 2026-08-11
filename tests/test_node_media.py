"""Control de reproducción en el nodo.

El motor de verdad son las sesiones multimedia de Windows, que no existen ni en
Linux ni en CI. Lo que sí se puede probar en cualquier sitio —y es donde están
los errores caros— es la frontera: a quién va la orden, qué pasa en un sistema
sin soporte y cómo se emparejan los títulos.
"""
import asyncio
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import capabilities, media  # noqa: E402
from vibi_node.config import NodeConfig  # noqa: E402

CONFIG = NodeConfig(
    url="https://vibi.local",
    node_id="nodo-1",
    token="nodo-1.secreto",
    nombre="Sobremesa",
    projects_root="/tmp",
)


class FronteraPorSistema(TestCase):
    def test_un_sistema_sin_soporte_lo_dice_en_vez_de_reventar(self):
        # macOS y Linux todavía no están escritos. Lo importante es que quien
        # lo pida se entere de por qué, no que salte un ImportError críptico.
        for sistema in ("Darwin", "Linux"):
            with patch("platform.system", return_value=sistema):
                with self.assertRaises(media.MediaError) as caso:
                    media.control("pause")
                self.assertIn("todavía no sabe", str(caso.exception))
                self.assertIn(sistema, str(caso.exception))

                with self.assertRaises(media.MediaError):
                    media.now_playing()

    def test_una_accion_inventada_se_rechaza_antes_de_tocar_el_sistema(self):
        # Se comprueba en Darwin: si el orden fuera el contrario, este caso
        # fallaría por «sin soporte» y no por la acción, que es lo que importa.
        with patch("platform.system", return_value="Darwin"):
            with self.assertRaises(media.MediaError) as caso:
                media.control("autodestruir")
        self.assertIn("autodestruir", str(caso.exception))
        self.assertIn("play", str(caso.exception))

    def test_falta_el_paquete_y_dice_cual(self):
        # Un Windows recién actualizado desde una versión anterior del agente
        # no tiene el paquete. El mensaje tiene que traer el remedio dentro.
        with patch.dict(sys.modules, {"winrt.windows.media.control": None}):
            with self.assertRaises(media.MediaError) as caso:
                media._cargar_windows()
        self.assertIn("winrt-Windows.Media.Control", str(caso.exception))


class EmparejarTitulos(TestCase):
    def test_reconoce_el_mismo_video_aunque_venga_recortado(self):
        # Nosotros recortamos a 120 caracteres al resolver el vídeo y YouTube
        # recorta por su cuenta: exigir igualdad exacta fallaría justo con los
        # títulos largos, que son los más frecuentes.
        largo = "lofi hip hop radio 📚 beats to relax/study to"
        self.assertTrue(media.coincide(largo, "lofi hip hop radio 📚"))
        self.assertTrue(media.coincide("lofi hip hop radio 📚", largo))
        self.assertTrue(media.coincide("  LOFI hip   hop radio 📚  ", largo))

    def test_no_confunde_dos_cosas_distintas(self):
        # Esto es lo que impide que un play destinado a un vídeo reanude el
        # Spotify que habías pausado a propósito.
        self.assertFalse(media.coincide("Bohemian Rhapsody", "lofi hip hop"))
        self.assertFalse(media.coincide(None, "lofi hip hop"))
        self.assertFalse(media.coincide("lofi hip hop", None))
        self.assertFalse(media.coincide("", ""))


class IdentificadorDeAplicacion(TestCase):
    def test_esconde_el_hash_del_navegador(self):
        # Medido en un Windows real: los navegadores se identifican así. Decir
        # «lo estás escuchando en F0DC299D809B9700» sería peor que no decirlo.
        self.assertIsNone(media._app_legible("F0DC299D809B9700"))
        self.assertIsNone(media._app_legible(None))

    def test_conserva_los_nombres_que_sí_se_entienden(self):
        self.assertEqual(media._app_legible("Spotify.exe"), "Spotify.exe")


class _EstadoFalso:
    PLAYING = "PLAYING"


class _SesionFalsa:
    """Una sesión que tarda en reflejar el cambio, como la de verdad."""

    def __init__(self, estados, app="Spotify.exe", titulo="Una canción"):
        self.estados = list(estados)
        self.lecturas = 0
        self.app = app
        self.titulo = titulo
        self.plays = 0
        self.pausas = 0

    @property
    def source_app_user_model_id(self):
        return self.app

    async def try_get_media_properties_async(self):
        class Props:
            title = self.titulo
            artist = "Alguien"

        return Props()

    def get_playback_info(self):
        indice = min(self.lecturas, len(self.estados) - 1)
        self.lecturas += 1

        class Info:
            playback_status = self.estados[indice]

        return Info()

    async def try_play_async(self):
        self.plays += 1
        return True

    async def try_pause_async(self):
        self.pausas += 1
        return True


class _ManagerFalso:
    def __init__(self, sesiones, actual=None):
        self.sesiones = list(sesiones)
        self.actual = actual

    def get_sessions(self):
        return list(self.sesiones)

    def get_current_session(self):
        return self.actual


class EsperarAlCambio(TestCase):
    def test_no_contesta_con_el_estado_de_antes(self):
        # Windows tarda un instante: preguntar de inmediato devolvía «sigue
        # sonando» justo después de pausar, y Vibi se creía que no había
        # funcionado.
        sesion = _SesionFalsa(["PLAYING", "PLAYING", "PAUSED"])
        with patch.object(media, "ASENTAMIENTO", 5.0):
            descripcion = asyncio.run(
                media._asentar(sesion, _EstadoFalso, "pause")
            )
        self.assertFalse(descripcion.sonando)

    def test_se_rinde_en_vez_de_quedarse_colgada(self):
        # Si el cambio no llega nunca —el reproductor lo ignoró— más vale
        # contestar el estado real que esperar eternamente.
        sesion = _SesionFalsa(["PLAYING"])
        with patch.object(media, "ASENTAMIENTO", 0.3):
            descripcion = asyncio.run(
                media._asentar(sesion, _EstadoFalso, "pause")
            )
        self.assertTrue(descripcion.sonando)


class LaVozDeVibiNoEsLoQueSuena(TestCase):
    """El companion corre sobre WebView2 y su voz registra una sesión propia.

    Medido en Windows 11: mientras Vibi habla, `get_current_session()`
    devuelve `msedgewebview2.exe` con el título «Vibi», así que un «pausa»
    a secas iba a callarla a ella en vez de a la música.
    """

    def test_una_orden_sin_titulo_esquiva_al_propio_companion(self):
        voz = _SesionFalsa(["PLAYING"], app="msedgewebview2.exe", titulo="Vibi")
        musica = _SesionFalsa(["PLAYING"], app="F0DC299D809B9700", titulo="Un vídeo")
        manager = _ManagerFalso([voz, musica], actual=voz)

        elegida = asyncio.run(media._elegir(manager, _EstadoFalso, None))
        self.assertIs(elegida, musica)

    def test_un_pausa_va_a_lo_que_suena_y_no_a_lo_ya_pausado(self):
        # Medido con varias pestañas: el sistema daba por «actual» una que
        # estaba pausada mientras sonaba otra, así que el pausa no callaba
        # nada y la música seguía.
        pausada = _SesionFalsa(["PAUSED"], app="F0DC299D809B9700", titulo="Vieja")
        sonando = _SesionFalsa(["PLAYING"], app="F0DC299D809B9700", titulo="Nueva")
        manager = _ManagerFalso([pausada, sonando], actual=pausada)

        elegida = asyncio.run(media._elegir(manager, _EstadoFalso, None))
        self.assertIs(elegida, sonando)

    def test_sin_nada_sonando_vale_la_que_el_sistema_considera_actual(self):
        # Es la que un «play» reanudaría, que es justo lo que quieres decir.
        una = _SesionFalsa(["PAUSED"], app="Spotify.exe", titulo="Una")
        otra = _SesionFalsa(["PAUSED"], app="F0DC299D809B9700", titulo="Otra")
        manager = _ManagerFalso([una, otra], actual=otra)

        elegida = asyncio.run(media._elegir(manager, _EstadoFalso, None))
        self.assertIs(elegida, otra)

    def test_si_no_hay_nada_mas_no_se_inventa_una_sesion(self):
        # Sin música de por medio, la respuesta honesta es que no suena nada
        # que se pueda controlar, no la voz de Vibi como premio de consuelo.
        voz = _SesionFalsa(["PLAYING"], app="msedgewebview2.exe", titulo="Vibi")
        manager = _ManagerFalso([voz], actual=voz)

        self.assertIsNone(asyncio.run(media._elegir(manager, _EstadoFalso, None)))


class ReconocerLaPestanaActiva(TestCase):
    """De qué habla la ventana que se está viendo.

    Es la única señal que distingue una pestaña de otra: el navegador expone
    una sola sesión multimedia para todas, pero la barra de título dice cuál
    tienes delante.
    """

    def test_reconoce_el_video_dentro_del_titulo_de_la_ventana(self):
        ventana = (
            "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)"
            " - YouTube — Zen Browser"
        )
        self.assertTrue(
            media.habla_de(ventana, "Rick Astley - Never Gonna Give You Up")
        )

    def test_no_confunde_la_pestaña_anterior_con_la_nueva(self):
        # Justo el fallo original: Zen enfoca la ventana antes de cambiar de
        # pestaña, así que durante un par de segundos la barra de título sigue
        # hablando del vídeo de antes.
        ventana = "Queen – Bohemian Rhapsody (Official Video) - YouTube — Zen Browser"
        self.assertFalse(media.habla_de(ventana, "Daft Punk - Get Lucky"))
        self.assertFalse(media.habla_de("", "Daft Punk - Get Lucky"))
        self.assertFalse(media.habla_de("Zen Browser", "Daft Punk - Get Lucky"))

    def test_una_ventana_generica_no_vale_por_cualquier_video(self):
        # La contención va en un solo sentido a propósito. Si valiera en los
        # dos, como en `coincide`, la ventana de remoting sin título o una
        # llamada «YouTube» a secas se darían por buenas y la pulsación
        # acabaría en la pestaña equivocada.
        self.assertFalse(media.habla_de("YouTube", "Un vídeo largo en YouTube"))
        self.assertFalse(media.habla_de("", ""))


class ArrancarElVideoReciénAbierto(TestCase):
    """Un vídeo que no suena todavía no existe para Windows.

    Medido: tras abrir dos pestañas nuevas, la sesión del navegador siguió
    cuarenta segundos anclada al vídeo anterior. Buscarlo por título no podía
    funcionar nunca, y el play a ciegas reanudaba el vídeo de antes.
    """

    def test_pulsa_una_sola_vez_cuando_la_ventana_del_video_está_delante(self):
        manager = _ManagerFalso([], actual=None)
        pulsaciones = []

        with patch.object(media, "_ventana_del_video", lambda _: 1234), patch.object(
            media, "_traer_al_frente", lambda _: True
        ), patch.object(
            media, "_pulsar_play_pausa", lambda: pulsaciones.append(1)
        ), patch.object(media, "INTERVALO_SONDEO", 0.01), patch.object(
            media, "CONFIRMACION", 0.05
        ):
            arrancado = asyncio.run(
                media._arrancar_pestana(manager, _EstadoFalso, "Un vídeo", 5.0)
            )

        self.assertEqual(len(pulsaciones), 1, "la tecla es un interruptor, no un play")
        self.assertTrue(arrancado)

    def test_espera_a_que_la_ventana_del_video_aparezca(self):
        # Medido: la pestaña tarda unos tres segundos en tener el vídeo. Antes
        # de eso no hay nada a lo que darle, y rendirse sería lo de siempre.
        manager = _ManagerFalso([], actual=None)
        intentos = []
        pulsaciones = []

        def ventana(_):
            intentos.append(1)
            return 1234 if len(intentos) >= 3 else None

        with patch.object(media, "_ventana_del_video", ventana), patch.object(
            media, "_traer_al_frente", lambda _: True
        ), patch.object(
            media, "_pulsar_play_pausa", lambda: pulsaciones.append(1)
        ), patch.object(media, "INTERVALO_SONDEO", 0.01), patch.object(
            media, "CONFIRMACION", 0.05
        ):
            arrancado = asyncio.run(
                media._arrancar_pestana(manager, _EstadoFalso, "Un vídeo", 5.0)
            )

        self.assertTrue(arrancado)
        self.assertEqual(len(pulsaciones), 1)

    def test_calla_lo_que_sonaba_antes_de_poner_lo_nuevo(self):
        # Abrir una pestaña no pausa la anterior: sin esto acabas oyendo dos
        # cosas a la vez, y como el navegador publica una sola sesión para
        # todas sus pestañas, el «pausa» siguiente iba a la vieja.
        vieja = _SesionFalsa(["PLAYING"], app="F0DC299D809B9700", titulo="Vídeo viejo")
        manager = _ManagerFalso([vieja], actual=vieja)

        with patch.object(media, "_ventana_del_video", lambda _: 1234), patch.object(
            media, "_traer_al_frente", lambda _: True
        ), patch.object(media, "_pulsar_play_pausa", lambda: None), patch.object(
            media, "INTERVALO_SONDEO", 0.01
        ), patch.object(media, "CONFIRMACION", 0.05):
            asyncio.run(
                media._arrancar_pestana(manager, _EstadoFalso, "Vídeo nuevo", 5.0)
            )

        self.assertEqual(vieja.pausas, 1)

    def test_no_calla_el_video_que_esta_poniendo(self):
        # Si el que suena ya es el que pediste, pausarlo sería apagar justo lo
        # que acabas de encender.
        nuestro = _SesionFalsa(["PLAYING"], app="F0DC299D809B9700", titulo="Vídeo")
        manager = _ManagerFalso([nuestro], actual=nuestro)

        with patch.object(media, "INTERVALO_SONDEO", 0.01):
            asyncio.run(media._callar_lo_anterior(manager, _EstadoFalso, "Vídeo"))

        self.assertEqual(nuestro.pausas, 0)

    def test_no_calla_a_vibi_hablando(self):
        # Su voz no es música de fondo que estorbe: es la respuesta a lo que
        # acabas de pedirle.
        voz = _SesionFalsa(["PLAYING"], app="msedgewebview2.exe", titulo="Vibi")
        manager = _ManagerFalso([voz], actual=voz)

        with patch.object(media, "INTERVALO_SONDEO", 0.01):
            asyncio.run(media._callar_lo_anterior(manager, _EstadoFalso, "Vídeo"))

        self.assertEqual(voz.pausas, 0)

    def test_no_toca_nada_si_el_video_arrancó_solo(self):
        # Si el navegador permitió el autoplay, pulsar sería pausarlo: el
        # usuario pidió verlo, no apagarlo.
        sonando = _SesionFalsa(["PLAYING"], app="F0DC299D809B9700", titulo="Un vídeo")
        manager = _ManagerFalso([sonando], actual=sonando)
        pulsaciones = []

        with patch.object(media, "_ventana_del_video", lambda _: 1234), patch.object(
            media, "_traer_al_frente", lambda _: True
        ), patch.object(
            media, "_pulsar_play_pausa", lambda: pulsaciones.append(1)
        ), patch.object(media, "INTERVALO_SONDEO", 0.01):
            arrancado = asyncio.run(
                media._arrancar_pestana(manager, _EstadoFalso, "Un vídeo", 5.0)
            )

        self.assertEqual(pulsaciones, [])
        self.assertTrue(arrancado)

    def test_no_escribe_en_la_ventana_de_otro(self):
        # Si estabas escribiendo en otra cosa cuando se abrió la pestaña, la
        # «k» acabaría dentro de tu editor. Más vale dejar el vídeo abierto y
        # sin arrancar que teclear en donde no toca.
        manager = _ManagerFalso([], actual=None)
        pulsaciones = []

        with patch.object(media, "_ventana_del_video", lambda _: None), patch.object(
            media, "_pulsar_play_pausa", lambda: pulsaciones.append(1)
        ), patch.object(media, "INTERVALO_SONDEO", 0.01):
            arrancado = asyncio.run(
                media._arrancar_pestana(manager, _EstadoFalso, "Un vídeo", 0.2)
            )

        self.assertEqual(pulsaciones, [])
        self.assertFalse(arrancado)

    def test_no_pulsa_si_no_consigue_poner_la_ventana_delante(self):
        # Windows puede negarle el primer plano a un proceso de fondo como el
        # agente. La ventana existe, pero la tecla iría a donde esté el foco,
        # que no es esta: pulsar sería teclear en la ventana de otro.
        manager = _ManagerFalso([], actual=None)
        pulsaciones = []

        with patch.object(media, "_ventana_del_video", lambda _: 1234), patch.object(
            media, "_traer_al_frente", lambda _: False
        ), patch.object(
            media, "_pulsar_play_pausa", lambda: pulsaciones.append(1)
        ), patch.object(media, "INTERVALO_SONDEO", 0.01):
            arrancado = asyncio.run(
                media._arrancar_pestana(manager, _EstadoFalso, "Un vídeo", 0.2)
            )

        self.assertEqual(pulsaciones, [])
        self.assertFalse(arrancado)


class CapacidadesDelNodo(TestCase):
    def test_el_agente_las_declara(self):
        # El agente anuncia lo que hay en HANDLERS al conectarse: si no están
        # aquí, el servidor cree que este dispositivo no sabe hacerlo.
        self.assertIn("media.control", capabilities.HANDLERS)
        self.assertIn("media.now_playing", capabilities.HANDLERS)

    def test_traduce_los_argumentos_y_solo_espera_con_titulo(self):
        vistos = []

        def falso(accion, titulo, espera):
            vistos.append((accion, titulo, espera))
            return {"accion": accion, "obedecida": True}

        with patch.object(media, "control", falso):
            capabilities.run(
                CONFIG,
                "media.control",
                {"accion": "PLAY", "titulo": "  Un vídeo  ", "espera": 10},
            )
            # Sin título no hay nada que esperar: bloquear el nodo diez
            # segundos a ver si aparece algo sería tiempo tirado.
            capabilities.run(CONFIG, "media.control", {"accion": "pause", "espera": 10})

        self.assertEqual(vistos[0], ("play", "Un vídeo", 10.0))
        self.assertEqual(vistos[1], ("pause", None, 0.0))

    def test_la_espera_no_puede_pasarse_de_lo_razonable(self):
        vistos = []
        with patch.object(
            media, "control", lambda a, t, e: vistos.append(e) or {}
        ):
            capabilities.run(
                CONFIG,
                "media.control",
                {"accion": "play", "titulo": "algo", "espera": 9_000},
            )
        self.assertEqual(vistos[0], media.ESPERA_SESION)

    def test_un_fallo_del_reproductor_llega_como_error_de_capacidad(self):
        # El cliente solo sabe traducir CapabilityError a un resultado con
        # estado «error»; cualquier otra cosa acaba en el manejador genérico.
        def revienta(*_):
            raise media.MediaError("No hay nada reproduciéndose")

        with patch.object(media, "now_playing", revienta):
            with self.assertRaises(capabilities.CapabilityError) as caso:
                capabilities.run(CONFIG, "media.now_playing", {})
        self.assertIn("No hay nada reproduciéndose", str(caso.exception))
