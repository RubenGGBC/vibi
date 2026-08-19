"""El ordenador entero: qué parte del disco se ve y quién lo sirve.

Lo que se prueba aquí son las costuras nuestras, no el protocolo MCP ni uvicorn.
Tres cosas: que la lista de sitios vetados no se esquiva por el camino fácil,
que las operaciones de archivo hacen lo que dicen —sobre todo `editar`, que es
la que evita reescribir archivos enteros de memoria— y que el servidor se le
declara al motor solo cuando de verdad hay una máquina sirviéndolo.
"""
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent.vibi_node import (
    capabilities,
    fs_scope,
    system_fs,
    system_mcp,
    system_shell,
)
from app import nodes, taint
from app.executors import agy_mcp_config


class ElDiscoPropioNoSeSirvePorMCP(unittest.TestCase):
    """Con el core en el ordenador del usuario, `pc_*` sobra.

    `agy` corre donde corre el core. Mientras eso era un contenedor, sus
    herramientas nativas veían un Linux vacío y hacía falta un servidor MCP
    que cruzara la frontera hasta el disco de verdad: eso es `pc_*`. Con el
    core nativo, `run_command` y `view_file` YA son ese disco, y mantener el
    servidor solo consigue ofrecerle dos caminos para lo mismo.

    Y no es gratis: comprobado contra el `agy` real el 19/08/2026 ya corriendo
    en Windows, el modelo gastó dos pasos en `view_file` de
    `mcp/pc/info.json` y `mcp/pc/ejecutar.json` antes de llamar a
    `pc_ejecutar`, teniendo su propia terminal a mano.

    La malla no se toca: si el disco que se sirve es el de OTRA máquina, el
    servidor sigue declarándose, porque ahí `agy` no llega solo.
    """

    def test_no_se_declara_cuando_el_disco_es_el_de_esta_maquina(self):
        from app.executors import agy_mcp_config

        self.assertTrue(agy_mcp_config.disco_alcanzable_sin_mcp("http://127.0.0.1:8933/x/mcp"))
        self.assertTrue(agy_mcp_config.disco_alcanzable_sin_mcp("http://localhost:8933/x/mcp"))

    def test_otra_maquina_de_la_malla_si_lo_necesita(self):
        from app.executors import agy_mcp_config

        self.assertFalse(
            agy_mcp_config.disco_alcanzable_sin_mcp("http://portatil.tailnet.ts.net:8933/x/mcp")
        )
        # El contenedor cuenta como «otra máquina»: es justo el caso de origen.
        self.assertFalse(
            agy_mcp_config.disco_alcanzable_sin_mcp("http://host.docker.internal:8933/x/mcp")
        )

    def test_con_disco_propio_el_servidor_pc_se_borra(self):
        from app.executors import agy_mcp_config

        class _Ajustes:
            google_mcp_servers = ""
            google_mcp_client_id = ""
            google_mcp_client_secret = ""
            system_mcp_host = "127.0.0.1"

        servidores = agy_mcp_config.construir_servidores(
            "u-1", "", _Ajustes(), "http://127.0.0.1:8933/secreto/mcp"
        )

        self.assertIsNone(servidores[agy_mcp_config.SERVIDOR_SISTEMA])

    def test_con_disco_ajeno_el_servidor_pc_se_mantiene(self):
        from app.executors import agy_mcp_config

        class _Ajustes:
            google_mcp_servers = ""
            google_mcp_client_id = ""
            google_mcp_client_secret = ""
            system_mcp_host = "portatil.tailnet.ts.net"

        url = "http://portatil.tailnet.ts.net:8933/secreto/mcp"
        servidores = agy_mcp_config.construir_servidores(
            "u-1", "", _Ajustes(), url
        )

        self.assertEqual(
            servidores[agy_mcp_config.SERVIDOR_SISTEMA], {"serverUrl": url}
        )


class DondeCorreElCore(unittest.TestCase):
    """El caso normal pasa a ser el ordenador del usuario, no el contenedor.

    Mientras el core vivía solo en Docker, `host.docker.internal` era el
    anfitrión y tenía sentido como valor por defecto. Con el core corriendo
    nativo —que es lo que hace que `agy` viva en el PC y sus herramientas
    nativas sean el disco de verdad— ese nombre no resuelve, y arrancar así
    dejaba a Vibi sin navegador y sin disco sin decir por qué.

    Docker sigue soportado: el `docker-compose.yml` pone los dos hosts por
    variable de entorno.
    """

    def test_por_defecto_apunta_a_la_maquina_local(self):
        from app.config import Settings

        ajustes = Settings(_env_file=None)

        self.assertEqual(ajustes.playwright_mcp_host, "127.0.0.1")
        self.assertEqual(ajustes.system_mcp_host, "127.0.0.1")

    def test_el_contenedor_lo_sobreescribe_por_entorno(self):
        from app.config import Settings

        with patch.dict(
            "os.environ",
            {
                "PLAYWRIGHT_MCP_HOST": "host.docker.internal",
                "SYSTEM_MCP_HOST": "host.docker.internal",
            },
            clear=False,
        ):
            ajustes = Settings(_env_file=None)

        self.assertEqual(ajustes.playwright_mcp_host, "host.docker.internal")
        self.assertEqual(ajustes.system_mcp_host, "host.docker.internal")


class LaCapacidadEstaDeclaradaEnLosDosLados(unittest.TestCase):
    """El nodo y el servidor validan por separado: ninguno se fía del otro.

    Y el servidor descarta en silencio lo que no conoce, así que una capacidad
    que solo esté en el agente no da error: simplemente no llega nunca.
    """

    def test_el_nodo_sabe_hacerla(self):
        self.assertIn("system.mcp", capabilities.HANDLERS)

    def test_el_servidor_la_acepta(self):
        self.assertIn("system.mcp", nodes.CAPABILITIES)

    def test_el_interruptor_del_dispositivo_la_apaga(self):
        """Da ejecución, así que tiene que respetar `shell_habilitado`."""
        self.assertNotIn("system.mcp", nodes.CAPACIDADES_LECTURA)


class ProteccionDelTransporte(unittest.TestCase):
    def test_docker_puede_usar_su_host_virtual_sin_desactivar_la_proteccion(self):
        mcp = system_mcp.construir_mcp("token", "127.0.0.1", 8933)

        security = mcp.settings.transport_security
        self.assertTrue(security.enable_dns_rebinding_protection)
        self.assertIn("host.docker.internal:*", security.allowed_hosts)
        self.assertIn("127.0.0.1:*", security.allowed_hosts)


class AsignacionDinamicaDePuertos(unittest.TestCase):
    def test_buscar_puerto_libre_encuentra_un_puerto_disponible(self):
        puerto = system_mcp.buscar_puerto_libre(8932, "127.0.0.1")
        self.assertGreater(puerto, 0)
        self.assertFalse(system_mcp.escuchando(puerto, "127.0.0.1"))

    def test_arrancar_encuentra_puerto_dinamico_si_esta_ocupado(self):
        with patch.object(system_mcp, "escuchando", side_effect=[True, False, True]), \
             patch.object(system_mcp, "_arrancar_hilo") as mock_arrancar:
            resultado = system_mcp.arrancar(8932, "127.0.0.1")
            self.assertEqual(resultado["estado"], "ok")
            mock_arrancar.assert_called_once()



class LoQueVibiNoAbre(unittest.TestCase):
    def test_la_carpeta_de_claves_esta_fuera(self):
        self.assertFalse(fs_scope.permitida(Path.home() / ".ssh" / "id_rsa"))

    def test_y_todo_lo_que_cuelgue_de_ella(self):
        self.assertFalse(fs_scope.permitida(Path.home() / ".ssh" / "sub" / "x.txt"))

    def test_un_env_lo_esta_viva_donde_viva(self):
        """Está en la raíz de casi todos sus proyectos: se cruza sin querer."""
        with TemporaryDirectory() as tmp:
            self.assertFalse(fs_scope.permitida(Path(tmp) / ".env"))
            self.assertFalse(fs_scope.permitida(Path(tmp) / ".env.produccion"))

    def test_un_archivo_normal_si(self):
        with TemporaryDirectory() as tmp:
            self.assertTrue(fs_scope.permitida(Path(tmp) / "notas.md"))

    def test_un_enlace_no_esquiva_la_lista(self):
        """Comparar cadenas dejaría entrar un symlink apuntando a ~/.ssh."""
        with TemporaryDirectory() as tmp:
            secreta = Path(tmp) / "secreta"
            secreta.mkdir()
            enlace = Path(tmp) / "atajo"
            try:
                enlace.symlink_to(secreta, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("este sistema no deja crear enlaces sin permisos")

            with patch.object(
                fs_scope, "carpetas_excluidas", return_value=(secreta.resolve(),)
            ):
                self.assertFalse(fs_scope.permitida(enlace / "clave"))

    def test_se_pueden_añadir_sitios_por_entorno(self):
        with TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {fs_scope.VARIABLE_EXCLUIR: "*.kdbx"}):
                self.assertFalse(fs_scope.permitida(Path(tmp) / "claves.kdbx"))

    def test_resolver_rechaza_lo_vetado_con_una_explicacion(self):
        with self.assertRaises(fs_scope.FueraDeAlcance) as fallo:
            fs_scope.resolver(str(Path.home() / ".ssh" / "config"))
        self.assertIn(fs_scope.VARIABLE_EXCLUIR, str(fallo.exception))


class LasRutasSalenAbsolutas(unittest.TestCase):
    """Quien pregunta está en otra máquina y no comparte nuestro cwd."""

    def test_una_relativa_se_entiende_contra_la_base(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            self.assertEqual(fs_scope.resolver("sub/x.txt", base), base / "sub/x.txt")


class LosArchivos(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)

    def test_listar_no_enseña_lo_que_no_deja_abrir(self):
        (self.base / "notas.md").write_text("hola", encoding="utf-8")
        (self.base / ".env").write_text("CLAVE=1", encoding="utf-8")

        nombres = [
            entrada["nombre"]
            for entrada in system_fs.listar(str(self.base), self.base)["entradas"]
        ]

        self.assertIn("notas.md", nombres)
        self.assertNotIn(".env", nombres)

    def test_leer_numera_las_lineas(self):
        archivo = self.base / "poema.txt"
        archivo.write_text("una\ndos\ntres\n", encoding="utf-8")

        salida = system_fs.leer(str(archivo), base=self.base)

        self.assertEqual(salida["contenido"], "1\tuna\n2\tdos\n3\ttres")
        self.assertEqual(salida["lineas_totales"], 3)

    def test_leer_un_tramo(self):
        archivo = self.base / "poema.txt"
        archivo.write_text("una\ndos\ntres\ncuatro\n", encoding="utf-8")

        salida = system_fs.leer(str(archivo), desde=2, lineas=2, base=self.base)

        self.assertEqual(salida["contenido"], "2\tdos\n3\ttres")
        self.assertTrue(salida["truncado"])

    def test_leer_algo_que_no_es_texto_lo_dice(self):
        archivo = self.base / "programa.bin"
        archivo.write_bytes(b"MZ\x00\x00binario")

        with self.assertRaises(system_fs.ErrorArchivo):
            system_fs.leer(str(archivo), base=self.base)

    def test_escribir_crea_las_carpetas_que_falten(self):
        destino = self.base / "uno" / "dos" / "nota.txt"

        system_fs.escribir(str(destino), "contenido", self.base)

        self.assertEqual(destino.read_text(encoding="utf-8"), "contenido")

    def test_editar_cambia_solo_el_fragmento(self):
        archivo = self.base / "codigo.py"
        archivo.write_text("uno\ndos\ntres\n", encoding="utf-8")

        system_fs.editar(str(archivo), "dos", "DOS", self.base)

        self.assertEqual(archivo.read_text(encoding="utf-8"), "uno\nDOS\ntres\n")

    def test_editar_se_niega_si_el_fragmento_esta_dos_veces(self):
        """Elegir la primera sería acertar la mitad de las veces en silencio."""
        archivo = self.base / "codigo.py"
        archivo.write_text("x = 1\nx = 1\n", encoding="utf-8")

        with self.assertRaises(system_fs.ErrorArchivo) as fallo:
            system_fs.editar(str(archivo), "x = 1", "x = 2", self.base)

        self.assertIn("2 veces", str(fallo.exception))
        self.assertEqual(archivo.read_text(encoding="utf-8"), "x = 1\nx = 1\n")

    def test_editar_se_niega_si_no_esta(self):
        archivo = self.base / "codigo.py"
        archivo.write_text("uno\n", encoding="utf-8")

        with self.assertRaises(system_fs.ErrorArchivo):
            system_fs.editar(str(archivo), "cuatro", "cinco", self.base)

    def test_buscar_por_nombre(self):
        (self.base / "sub").mkdir()
        (self.base / "sub" / "factura.pdf").write_text("x", encoding="utf-8")
        (self.base / "otra.txt").write_text("x", encoding="utf-8")

        encontrados = system_fs.buscar("**/*.pdf", str(self.base), base=self.base)

        self.assertEqual(len(encontrados["archivos"]), 1)
        self.assertTrue(encontrados["archivos"][0].endswith("factura.pdf"))

    def test_buscar_por_contenido(self):
        (self.base / "uno.txt").write_text("aquí pone naranja\n", encoding="utf-8")
        (self.base / "dos.txt").write_text("aquí no\n", encoding="utf-8")

        # Sin ripgrep en la máquina el camino es otro, y los dos tienen que dar
        # lo mismo: se prueba el de Python, que es el que siempre está.
        with patch.object(system_fs, "_rg", return_value=None):
            hallazgos = system_fs.buscar(
                texto="naranja", ruta=str(self.base), base=self.base
            )

        self.assertEqual(len(hallazgos["coincidencias"]), 1)
        self.assertTrue(hallazgos["coincidencias"][0]["ruta"].endswith("uno.txt"))

    def test_buscar_por_contenido_no_mira_dentro_de_lo_vetado(self):
        (self.base / ".env").write_text("CLAVE=naranja\n", encoding="utf-8")

        with patch.object(system_fs, "_rg", return_value=None):
            hallazgos = system_fs.buscar(
                texto="naranja", ruta=str(self.base), base=self.base
            )

        self.assertEqual(hallazgos["coincidencias"], [])


class LosComandosLargos(unittest.TestCase):
    """El par lanzar/progreso es la razón de que este módulo exista.

    Lo que ya había competía contra los 45 s que una conversación aguanta
    esperando, así que nada que durara más se podía pedir.
    """

    def test_un_trabajo_lanzado_vuelve_al_instante_y_luego_se_consulta(self):
        lanzado = system_shell.lanzar("echo hola")
        self.addCleanup(lambda: system_shell.parar(lanzado["trabajo"]))

        self.assertIn("trabajo", lanzado)

        for _ in range(100):
            estado = system_shell.salida(lanzado["trabajo"])
            if estado["terminado"]:
                break
            time.sleep(0.1)

        self.assertTrue(estado["terminado"])
        self.assertEqual(estado["codigo"], 0)
        self.assertIn("hola", estado["salida"])

    def test_preguntar_por_un_trabajo_que_no_existe(self):
        with self.assertRaises(system_shell.ErrorShell):
            system_shell.salida("noexiste")

    def test_el_interprete_de_windows_es_powershell(self):
        """`shell=True` daría cmd.exe, donde no funciona nada de lo escrito
        para Windows en los últimos quince años."""
        with patch("platform.system", return_value="Windows"), \
             patch("shutil.which", side_effect=lambda n: f"C:\\{n}.exe"):
            argv = system_shell.interprete()

        self.assertIn("pwsh", argv[0])
        self.assertIn("-NoProfile", argv)


class ComoSeLeDeclaraAlMotor(unittest.TestCase):
    def test_con_maquina_sirviendo_se_declara(self):
        servidores = agy_mcp_config.construir_servidores(
            "u1", "", _AjustesPelados(), "http://host.docker.internal:8932/xyz/mcp"
        )

        self.assertEqual(
            servidores[agy_mcp_config.SERVIDOR_SISTEMA],
            {"serverUrl": "http://host.docker.internal:8932/xyz/mcp"},
        )

    def test_sin_maquina_la_entrada_se_borra(self):
        """`None` significa «borra esto», no «déjalo como esté»: una entrada
        que sobrevive a su servidor le cuesta el arranque entero a `agy`."""
        servidores = agy_mcp_config.construir_servidores(
            "u1", "", _AjustesPelados()
        )

        self.assertIsNone(servidores[agy_mcp_config.SERVIDOR_SISTEMA])

    def test_cuenta_como_fuente_de_texto_ajeno(self):
        """Los archivos son «suyos», pero un PDF que se bajó lo escribió otro."""
        self.assertIn(
            agy_mcp_config.SERVIDOR_SISTEMA, agy_mcp_config.SERVIDORES_EXTERNOS
        )
        self.assertIn(
            f"agy.{agy_mcp_config.SERVIDOR_SISTEMA}", taint.FUENTES_EXTERNAS
        )

    def test_solo_se_vigila_cuando_esta_en_pie(self):
        ajustes = _AjustesPelados()

        self.assertNotIn(
            agy_mcp_config.SERVIDOR_SISTEMA,
            agy_mcp_config.servidores_externos(ajustes),
        )
        self.assertIn(
            agy_mcp_config.SERVIDOR_SISTEMA,
            agy_mcp_config.servidores_externos(ajustes, sistema=True),
        )


class _AjustesPelados:
    """Los ajustes mínimos que mira `construir_servidores`, sin credenciales."""

    google_mcp_client_id = ""
    google_mcp_client_secret = ""
    google_mcp_servers = ""


if __name__ == "__main__":
    unittest.main()


class ElTopeDeLasOrdenesCabeEnLoQueAgyEspera(unittest.TestCase):
    """El nodo tiene que rendirse antes que `agy`, no después.

    `agy` cancela una llamada MCP alrededor del minuto, y su cancelación no es
    inocua: el ejecutor de la conversación se queda con el turno a medias y
    rechaza el siguiente con «SendUserMessage failed: executor has not
    processed the previous input yet». La conversación queda inservible.

    Medido el 17 de agosto de 2026 con un `Get-ChildItem -Recurse -Force` sobre
    el perfil entero, que es lo que el modelo escribe solo cuando le preguntas
    si tienes instalado un programa. Con el tope del nodo por debajo, quien
    contesta es el nodo —con un texto que dice qué hacer— y el modelo puede
    seguir hablando en vez de colgarse.
    """

    def _herramienta(self):
        mcp = system_mcp.construir_mcp("token", "127.0.0.1", 8933)
        return mcp._tool_manager.get_tool("ejecutar").fn

    def test_el_tope_deja_margen_antes_de_que_agy_cancele(self):
        self.assertLess(system_mcp.TIMEOUT_ORDEN_MAX, 60)

    def test_lo_que_pida_de_mas_se_recorta(self):
        with patch.object(system_shell, "ejecutar", return_value={}) as ejecutar:
            self._herramienta()(comando="dir", timeout=600)

        self.assertEqual(
            ejecutar.call_args.args[2], system_mcp.TIMEOUT_ORDEN_MAX
        )

    def test_una_espera_mas_corta_se_respeta(self):
        with patch.object(system_shell, "ejecutar", return_value={}) as ejecutar:
            self._herramienta()(comando="dir", timeout=5)

        self.assertEqual(ejecutar.call_args.args[2], 5)

    def test_el_modelo_ve_el_tope_en_el_esquema(self):
        """Lo lee de aquí para decidir: si dice 120, pedirá 120."""
        mcp = system_mcp.construir_mcp("token", "127.0.0.1", 8933)
        esquema = mcp._tool_manager.get_tool("ejecutar").parameters

        self.assertEqual(
            esquema["properties"]["timeout"]["default"],
            system_mcp.TIMEOUT_ORDEN_MAX,
        )


class BuscarSeRindeATiempo(unittest.TestCase):
    r"""Una búsqueda sin fondo es lo que colgaba a `agy`.

    El 2026-08-17, «mírame si tengo el CEMU instalado» acabó en
    `buscar(patron="*zemu*", ruta="C:\Users\rebel")`. Como no existe ningún
    archivo así, `rglob` no encontraba nada que contar y recorría el perfil
    entero —AppData y todos los `node_modules` dentro— sin cortar jamás:
    `MAX_RESULTADOS` solo frena cuando hay resultados. `agy` cancelaba la
    llamada al minuto y esa cancelación deja la conversación inservible.

    Cortar por reloj y devolver lo que se lleve encontrado es mejor que un
    error: para saber si un programa está instalado, lo que aparezca en los
    primeros segundos suele bastar.
    """

    def test_devuelve_lo_que_tenga_cuando_se_le_acaba_el_tiempo(self):
        with TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            (raiz / "hondo").mkdir()
            (raiz / "hondo" / "zemu.exe").touch()

            resultado = system_fs.buscar(
                patron="*zemu*", ruta=str(raiz), base=raiz, limite_segundos=0
            )

        self.assertTrue(resultado["truncado"])
        self.assertIn("aviso", resultado)
        self.assertIn("acota", resultado["aviso"].lower())

    def test_con_tiempo_de_sobra_encuentra_lo_que_hay(self):
        with TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            (raiz / "hondo").mkdir()
            (raiz / "hondo" / "zemu.exe").touch()

            resultado = system_fs.buscar(patron="*zemu*", ruta=str(raiz), base=raiz)

        self.assertEqual(len(resultado["archivos"]), 1)
        self.assertFalse(resultado["truncado"])
        self.assertNotIn("aviso", resultado)

    def test_el_tope_deja_margen_antes_de_que_agy_cancele(self):
        self.assertLess(system_fs.BUSQUEDA_SEGUNDOS, 60)

    def test_la_herramienta_lo_pasa_igual_que_ejecutar(self):
        """Sin esto el tope existiría pero nadie lo usaría."""
        mcp = system_mcp.construir_mcp("token", "127.0.0.1", 8933)
        with patch.object(system_fs, "buscar", return_value={}) as buscar:
            mcp._tool_manager.get_tool("buscar").fn(patron="*zemu*")

        self.assertIn(system_mcp.TIMEOUT_ORDEN_MAX, buscar.call_args.args)
