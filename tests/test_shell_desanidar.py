"""Quitar el PowerShell de dentro del PowerShell.

El modelo escribe `powershell -Command "…"` constantemente y se entiende: es lo
que aparece en toda la documentación de Windows. Pero el comando ya se ejecuta
dentro de PowerShell, así que arranca un intérprete dentro del intérprete.

En el histórico de este equipo, los cuatro comandos más lentos de `shell.run`
empiezan así. Medido el 20/08/2026: **596 ms contra 375 ms**. Y el sobrecoste no
es lo peor — el que arranca dentro es `powershell.exe`, el 5.1, con otra
sintaxis y otra codificación que las de pwsh 7, en el que estaba escrito lo que
se le pasa.

La regla al desenvolver es la de siempre: **ante la duda, no tocar**. Ejecutar
algo distinto de lo que te han pedido es mucho peor que ejecutarlo lento.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node.system_shell import desanidar  # noqa: E402


class LoQueSeDesenvuelve(TestCase):
    def test_la_forma_de_siempre(self):
        self.assertEqual(
            desanidar('powershell -Command "Get-Date"'), "Get-Date"
        )

    def test_con_el_ejecutable_entero(self):
        self.assertEqual(
            desanidar('powershell.exe -Command "Get-Process"'), "Get-Process"
        )

    def test_pwsh_también(self):
        self.assertEqual(desanidar("pwsh -Command 'Get-Date'"), "Get-Date")

    def test_con_la_c_abreviada(self):
        self.assertEqual(desanidar('powershell -c "Get-Date"'), "Get-Date")

    def test_con_los_flags_que_suele_llevar(self):
        self.assertEqual(
            desanidar('powershell -NoProfile -NonInteractive -Command "ls"'),
            "ls",
        )

    def test_las_comillas_escapadas_de_dentro_se_deshacen(self):
        """Es el caso real del histórico: rutas entrecomilladas dentro."""
        salida = desanidar(
            'powershell -Command "Get-ChildItem -Path \\"$env:LOCALAPPDATA\\""'
        )
        self.assertEqual(salida, 'Get-ChildItem -Path "$env:LOCALAPPDATA"')

    def test_una_tubería_dentro_sobrevive_entera(self):
        salida = desanidar(
            'powershell -Command "Get-Process | Select-Object -First 3"'
        )
        self.assertEqual(salida, "Get-Process | Select-Object -First 3")


class LoQueNoSeToca(TestCase):
    def test_un_comando_normal(self):
        self.assertEqual(desanidar("Get-Date"), "Get-Date")

    def test_powershell_con_algo_detrás_no_es_un_envoltorio(self):
        """`… | Out-File` fuera de las comillas cambia lo que hace el comando."""
        crudo = 'powershell -Command "Get-Date" | Out-File x.txt'
        self.assertEqual(desanidar(crudo), crudo)

    def test_powershell_con_un_script_no_es_un_envoltorio(self):
        crudo = "powershell -File instalar.ps1"
        self.assertEqual(desanidar(crudo), crudo)

    def test_sin_comillas_no_se_toca(self):
        crudo = "powershell -Command Get-Date"
        self.assertEqual(desanidar(crudo), crudo)

    def test_powershell_en_medio_del_comando_no_se_toca(self):
        crudo = 'echo hola && powershell -Command "Get-Date"'
        self.assertEqual(desanidar(crudo), crudo)

    def test_un_envoltorio_vacío_se_deja_como_está(self):
        crudo = 'powershell -Command ""'
        self.assertEqual(desanidar(crudo), crudo)

    def test_lo_vacío_sigue_vacío(self):
        self.assertEqual(desanidar(""), "")
        self.assertEqual(desanidar(None), "")

    def test_una_palabra_que_empieza_por_powershell_no_cuenta(self):
        crudo = "powershellinstalador -Command \"x\""
        self.assertEqual(desanidar(crudo), crudo)
