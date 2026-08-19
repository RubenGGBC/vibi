"""Instalar la CLI de Antigravity sin mandar al usuario a una página web.

`agy` no está en npm —comprobado en el registro el 19/08/2026:
`@google/antigravity-cli` no existe, y el `antigravity-cli` que sí está es de un
tercero, de 2025, y su binario se llama `kirox`—. Lo que Google publica son dos
guiones oficiales, uno por familia de sistema, y es lo que se ejecuta aquí: su
lógica de descarga cambia cuando ellos quieran, y replicarla obligaría a
perseguirles.

Lo que se prueba es la costura nuestra: que cada sistema reciba su guion, que
no se invente uno donde no lo hay, y que el binario se encuentre después aunque
el PATH de este proceso no se haya enterado todavía.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from installer import agy


class CadaSistemaRecibeSuGuion(unittest.TestCase):
    def test_windows_va_por_powershell(self):
        comando = agy.comando_de_instalacion("windows")

        self.assertIn("powershell", comando[0].lower())
        self.assertTrue(any("install.ps1" in parte for parte in comando))

    def test_mac_y_linux_van_por_bash(self):
        for so in ("macos", "linux"):
            comando = agy.comando_de_instalacion(so)

            self.assertTrue(any("install.sh" in parte for parte in comando), so)
            self.assertTrue(any("bash" in parte for parte in comando), so)

    def test_un_sistema_desconocido_no_se_intenta(self):
        """Antes de descargar y ejecutar algo, hay que saber qué se ejecuta."""
        with self.assertRaises(agy.NoSePuedeInstalar):
            agy.comando_de_instalacion("desconocido")

    def test_windows_no_hereda_el_perfil_del_usuario(self):
        """`-NoProfile` para que un perfil de PowerShell con manías no cambie
        lo que hace el guion oficial a mitad de instalación."""
        self.assertIn("-NoProfile", agy.comando_de_instalacion("windows"))


class EncontrarloDespuesDeInstalarlo(unittest.TestCase):
    def test_lo_busca_donde_lo_deja_el_guion_oficial(self):
        """El PATH de este proceso se fijó al arrancar y no se entera de que
        acaba de aparecer un ejecutable nuevo. Sin mirar en el sitio conocido,
        el instalador diría que `agy` sigue sin estar justo después de haberlo
        instalado bien."""
        with TemporaryDirectory() as casa:
            destino = Path(casa) / "AppData" / "Local" / "agy" / "bin"
            destino.mkdir(parents=True)
            binario = destino / "agy.exe"
            binario.write_text("", encoding="utf-8")

            # `LOCALAPPDATA` es la que usa el guion oficial (`Join-Path
            # $env:LOCALAPPDATA "agy\\bin"`), así que es la que manda aquí.
            with patch("platform.system", return_value="Windows"), patch.object(
                agy.Path, "home", return_value=Path(casa)
            ), patch("shutil.which", return_value=None), patch.dict(
                "os.environ", {"LOCALAPPDATA": str(Path(casa) / "AppData" / "Local")}
            ):
                encontrado = agy.donde_esta()

        self.assertEqual(Path(encontrado), binario)

    def test_si_esta_en_el_path_se_usa_ese(self):
        with patch("shutil.which", return_value="/usr/local/bin/agy"):
            self.assertEqual(agy.donde_esta(), "/usr/local/bin/agy")

    def test_si_no_esta_en_ninguna_parte_lo_dice(self):
        with patch("shutil.which", return_value=None), patch.object(
            agy, "_candidatos", return_value=()
        ):
            self.assertEqual(agy.donde_esta(), "")


if __name__ == "__main__":
    unittest.main()
