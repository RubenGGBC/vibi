"""Actualizar Vibi desde el repositorio, sin llevarse nada por delante.

Lo que se prueba aquí no es que `git` funcione, sino las dos decisiones que
tomamos encima: cuándo hay algo nuevo que ofrecer, y cuándo NO se puede
actualizar porque el usuario tiene trabajo sin guardar. Lo segundo es lo que
separa un botón útil de uno que te borra la tarde.
"""
import unittest
from unittest.mock import patch

from installer import actualizacion


class _Git:
    """Sustituye a `git` devolviendo lo que cada subcomando debería decir.

    Imita el recorte de la salida que hace el `_git` de verdad, y no es un
    detalle: ese recorte se comía el primer carácter de la primera línea del
    `status`, donde la columna de estado es significativa. Un doble que
    devolviera la cadena intacta daría por bueno justo el fallo que hay que
    cazar.
    """

    def __init__(self, respuestas, fallan=()):
        self.respuestas = respuestas
        self.fallan = set(fallan)
        self.llamadas = []

    def __call__(self, args, **kwargs):
        self.llamadas.append(args)
        clave = args[0]
        if clave in self.fallan:
            raise actualizacion.GitError(f"falló {clave}")
        crudo = self.respuestas.get(clave, "")
        return crudo if kwargs.get("conservar_espacios") else crudo.strip()


class SaberSiHayAlgoNuevo(unittest.TestCase):
    def test_con_el_remoto_por_delante_hay_novedades(self):
        git = _Git({"rev-list": "3", "log": "una cosa\notra\nla tercera"})

        with patch.object(actualizacion, "_git", git):
            novedades = actualizacion.novedades()

        self.assertTrue(novedades.hay)
        self.assertEqual(novedades.commits, 3)
        self.assertEqual(len(novedades.titulos), 3)

    def test_al_dia_no_molesta(self):
        git = _Git({"rev-list": "0"})

        with patch.object(actualizacion, "_git", git):
            novedades = actualizacion.novedades()

        self.assertFalse(novedades.hay)
        self.assertEqual(novedades.commits, 0)

    def test_sin_red_no_se_inventa_una_actualizacion(self):
        """Un `fetch` fallido no puede leerse como «estás al día» ni como
        «hay novedades»: las dos mentiras llevan a decisiones malas."""
        git = _Git({}, fallan=("fetch",))

        with patch.object(actualizacion, "_git", git):
            novedades = actualizacion.novedades()

        self.assertFalse(novedades.hay)
        self.assertTrue(novedades.problema)


class NoPisarElTrabajoDeNadie(unittest.TestCase):
    def test_con_cambios_sin_guardar_no_actualiza(self):
        """`git pull` ahí puede dejar el árbol en conflicto a medias, y quien
        lo sufre no es quien lo entiende: es alguien que solo quería el botón."""
        git = _Git({"status": " M app/api.py\n"})

        with patch.object(actualizacion, "_git", git):
            with self.assertRaises(actualizacion.HayTrabajoSinGuardar):
                actualizacion.actualizar()

        self.assertNotIn(["pull"], [c[:1] for c in git.llamadas])

    def test_con_el_arbol_limpio_actualiza(self):
        git = _Git({"status": "", "rev-list": "2", "log": "algo\nmas"})

        with patch.object(actualizacion, "_git", git):
            actualizacion.actualizar()

        subcomandos = [c[0] for c in git.llamadas]
        self.assertIn("pull", subcomandos)

    def test_el_primer_nombre_no_pierde_su_primera_letra(self):
        """En `--porcelain` la columna de estado son dos caracteres, y el
        primero puede ser un espacio. Recortar la salida entera se lo come solo
        a la primera línea, y el aviso salía diciendo «env.example» por
        «.env.example» y «gent/...» por «agent/...». Se ve raro y hace dudar de
        si el instalador entiende lo que está mirando.
        """
        git = _Git({"status": " M .env.example\n M README.md\n"})

        with patch.object(actualizacion, "_git", git):
            with self.assertRaises(actualizacion.HayTrabajoSinGuardar) as caso:
                actualizacion.actualizar()

        self.assertIn(".env.example", str(caso.exception))
        self.assertIn("README.md", str(caso.exception))

    def test_los_archivos_sin_seguimiento_no_bloquean(self):
        """`data/`, `.env` y los logs salen ahí siempre y no estorban al pull."""
        git = _Git({"status": "?? notas.txt\n?? data/prueba.db\n"})

        with patch.object(actualizacion, "_git", git):
            actualizacion.actualizar()

        self.assertIn("pull", [c[0] for c in git.llamadas])


if __name__ == "__main__":
    unittest.main()
