"""Leer el centro de notificaciones de macOS, que es una base de datos.

Windows presta una API para esto —`UserNotificationListener`— y macOS no presta
ninguna: lo único que hay es la SQLite que `usernoted` va escribiendo en
`~/Library/Group Containers/group.com.apple.usernoted/db2/db`, con los textos
metidos dentro de un *binary plist* en una columna `data`.

Las pruebas se hacen contra una base fabricada aquí con esa forma, no contra la
del sistema: la de verdad está detrás de Acceso a disco completo y no hay Mac de
integración continua que la tenga. Lo que se comprueba es el descodificado y la
identidad de cada aviso; que el esquema del sistema sea este se confirma con
`python -m vibi_node.notifications_macos` en una máquina con el permiso dado.
"""
from __future__ import annotations

import plistlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import notifications_macos as N  # noqa: E402


def _base(registros: list[dict]) -> Path:
    """Fabrica una base con la forma de la de `usernoted`.

    `registros` lleva diccionarios con lo que interesa de cada fila; el resto de
    columnas se rellenan con algo plausible para que el SELECT real funcione.
    """
    carpeta = Path(tempfile.mkdtemp())
    ruta = carpeta / "db"
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE app (app_id INTEGER PRIMARY KEY, identifier VARCHAR)")
    con.execute(
        "CREATE TABLE record (rec_id INTEGER PRIMARY KEY, app_id INTEGER, "
        "uuid BLOB, data BLOB, request_date REAL, presented INTEGER, "
        "delivered_date REAL)"
    )
    apps: dict[str, int] = {}
    for fila in registros:
        bundle = fila.get("bundle", "com.hnc.Discord")
        if bundle not in apps:
            apps[bundle] = len(apps) + 1
            con.execute(
                "INSERT INTO app (app_id, identifier) VALUES (?, ?)",
                (apps[bundle], bundle),
            )
        datos = fila.get("data")
        if datos is None:
            peticion = {
                k: v
                for k, v in (
                    ("titl", fila.get("titl")),
                    ("subt", fila.get("subt")),
                    ("body", fila.get("body")),
                )
                if v is not None
            }
            datos = plistlib.dumps({"req": peticion}, fmt=plistlib.FMT_BINARY)
        con.execute(
            "INSERT INTO record (rec_id, app_id, uuid, data, request_date, "
            "presented, delivered_date) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (
                fila.get("rec_id", 1),
                apps[bundle],
                fila.get("uuid", b"\x01\x02\x03\x04"),
                datos,
                fila.get("request_date", 0.0),
                fila.get("request_date", 0.0),
            ),
        )
    con.commit()
    con.close()
    return ruta


class LeerLaBase(TestCase):
    def test_saca_el_titulo_y_el_cuerpo_de_la_notificacion(self):
        """Los textos no están en columnas: van dentro del plist de `data`."""
        ruta = _base([{"titl": "Ana", "body": "¿Quedamos mañana?"}])

        avisos = N.leer(ruta)

        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0].titulo, "Ana")
        self.assertEqual(avisos[0].cuerpo, "¿Quedamos mañana?")


class LaIdentidadDeUnAviso(TestCase):
    """Por qué la clave es el UUID y no el número de fila.

    macOS borra la fila cuando descartas la notificación, y `rec_id` es un
    INTEGER PRIMARY KEY: ese número vuelve a estar libre y se lo queda la
    siguiente. Con `rec_id` de clave, el `Vigia` daría por visto un aviso que
    acaba de llegar y no te lo contaría nunca. En Windows no pasa —sus ids
    crecen y no se reciclan—, así que esto es propio de aquí.
    """

    def test_un_rec_id_reciclado_sigue_siendo_un_aviso_nuevo(self):
        vigia = N.Vigia()
        vigia.novedades(N.leer(_base([{"rec_id": 1, "uuid": b"AAAA", "titl": "Ana"}])))

        # Descartas la de Ana y llega otra: macOS reutiliza el hueco del 1.
        nuevas = vigia.novedades(
            N.leer(_base([{"rec_id": 1, "uuid": b"BBBB", "titl": "Marcos"}]))
        )

        self.assertEqual([a.titulo for a in nuevas], ["Marcos"])


class AguantarLoQueVengaMal(TestCase):
    """La base la escribe el sistema, no nosotros, y trae de todo.

    Una sola fila rara no puede dejar a Vibi muda: el resto del centro sigue
    siendo perfectamente legible.
    """

    def test_una_fila_ilegible_no_se_lleva_por_delante_a_las_demas(self):
        ruta = _base(
            [
                {"rec_id": 1, "uuid": b"AAAA", "data": b"esto no es un plist"},
                {"rec_id": 2, "uuid": b"BBBB", "titl": "Ana", "body": "hola"},
            ]
        )

        avisos = N.leer(ruta)

        self.assertEqual([a.titulo for a in avisos], ["Ana"])

    def test_una_notificacion_sin_titulo_conserva_el_cuerpo(self):
        """Media aplicación manda solo `body`, sin `titl`."""
        ruta = _base([{"body": "Se ha completado la copia de seguridad"}])

        avisos = N.leer(ruta)

        self.assertEqual(avisos[0].titulo, "")
        self.assertEqual(avisos[0].cuerpo, "Se ha completado la copia de seguridad")


class ArmarElTextoYLaHora(TestCase):
    def test_el_subtitulo_entra_en_el_cuerpo(self):
        """En un grupo de WhatsApp el título es el grupo y el subtítulo, quién habla.

        Perderlo dejaría «Cena del viernes: yo llevo el postre» sin decir quién
        lo lleva, que es justo lo que hace falta para contestar.
        """
        ruta = _base(
            [{"titl": "Cena del viernes", "subt": "Marcos", "body": "yo llevo el postre"}]
        )

        avisos = N.leer(ruta)

        self.assertEqual(avisos[0].titulo, "Cena del viernes")
        self.assertEqual(avisos[0].cuerpo, "Marcos: yo llevo el postre")

    def test_la_hora_sale_en_iso_y_no_en_el_epoch_de_apple(self):
        """Apple cuenta los segundos desde 2001, no desde 1970.

        Pasar el número tal cual dejaría la fecha treinta y un años corta.
        """
        ruta = _base([{"titl": "Ana", "request_date": 780000000.0}])

        avisos = N.leer(ruta)

        self.assertEqual(avisos[0].cuando, "2025-09-19T18:40:00+00:00")


class SaberSiSePuedeLeer(TestCase):
    """Sin Acceso a disco completo la base no se abre, y hay que decirlo.

    Es la única comprobación de permiso que hay en macOS: no existe una API que
    pregunte «¿me dejas?», así que intentar abrirla *es* preguntar.
    """

    def test_no_esta_disponible_si_no_se_puede_abrir_la_base(self):
        self.assertFalse(N.disponible(Path("/no/existe/db")))

    def test_esta_disponible_si_la_base_se_deja_leer(self):
        self.assertTrue(N.disponible(_base([{"titl": "Ana"}])))


class ComoSeLlamaLaAplicacion(TestCase):
    """La base guarda `com.hnc.Discord`, y eso acaba en boca de Vibi.

    El servidor pasa `app` al modelo tal cual —`sanear()` en `app/avisos.py`—,
    así que «te escriben por com.hnc.Discord» es lo que oirías.
    """

    def test_si_spotlight_no_conoce_el_bundle_se_usa_el_identificador(self):
        """Feo, pero cierto. Inventarse un nombre sería peor."""
        ruta = _base([{"bundle": "com.vibi.inventado.que.no.existe", "titl": "Ana"}])

        avisos = N.leer(ruta)

        self.assertEqual(avisos[0].app, "com.vibi.inventado.que.no.existe")

    def test_no_le_pregunta_a_spotlight_dos_veces_por_la_misma(self):
        """Se sondea cada segundo y medio: sin cache serían cuatro procesos por sondeo."""
        cache = {"com.hnc.Discord": "Discord"}

        self.assertEqual(N._nombre_de_app("com.hnc.Discord", cache), "Discord")


class Autodiagnostico(TestCase):
    """`python -m vibi_node.notifications_macos` en la máquina del usuario.

    Las pruebas de arriba van contra una base fabricada aquí, así que confirman
    el descodificado pero **no** que el sistema guarde las notificaciones con
    esta forma. Eso solo se sabe mirando la base de verdad, que necesita Acceso
    a disco completo. Esto es lo que lo mira.
    """

    def test_sin_permiso_dice_que_falta_y_como_darlo(self):
        """La base está ahí y no se deja abrir: eso es TCC, y tiene arreglo."""
        ruta = _base([{"titl": "Ana"}])
        ruta.chmod(0o000)
        self.addCleanup(ruta.chmod, 0o644)

        informe = N.diagnostico(ruta)

        self.assertIn("Acceso a disco completo", informe)

    def test_si_la_base_no_esta_no_habla_de_permisos(self):
        """Un fichero que no existe no es un permiso denegado, y confundirlos
        mandaría al usuario a Ajustes del Sistema a no arreglar nada."""
        informe = N.diagnostico(Path("/no/existe/db"))

        self.assertNotIn("Acceso a disco completo", informe)

    def test_con_permiso_cuenta_lo_que_ha_sabido_leer(self):
        ruta = _base(
            [
                {"rec_id": 1, "uuid": b"AAAA", "titl": "Ana", "body": "hola"},
                {"rec_id": 2, "uuid": b"BBBB", "titl": "Marcos"},
            ]
        )

        informe = N.diagnostico(ruta)

        self.assertIn("2", informe)
        self.assertNotIn("Acceso a disco completo", informe)


if __name__ == "__main__":
    unittest.main()
