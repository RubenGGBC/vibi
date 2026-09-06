"""Relevo: del contexto efimero del nodo al manifiesto que recibe el motor."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import relevo, ui_windows  # noqa: E402

from app import nodes, tools  # noqa: E402
from app.executors import agy_mcp, antigravity_chat  # noqa: E402


ARBOL = '''ventana con foco: "Solicitud de beca"

[e1] campo "Nombre" = "Ana"
[e2] campo "Certificado academico"
[e3] casilla "Acepto las condiciones" (marcado)
[e4] boton "Enviar solicitud"

4 nodos'''


class ManifiestoDelNodo(TestCase):
    def setUp(self):
        relevo.olvidar()

    def _captura(self):
        return {
            "arbol": ARBOL,
            "ventana": "Solicitud de beca",
            "nodos": 4,
            "omitidos": 0,
            "vacio": False,
            "ms": 12,
        }

    def test_primero_reconstruye_y_espera_sin_actuar(self):
        with patch.object(relevo.ui, "capturar", return_value=self._captura()):
            manifiesto = relevo.preparar()

        self.assertEqual(manifiesto["schema"], "vibi.relevo.desktop.v1")
        self.assertEqual(manifiesto["estado"], "esperando_confirmacion")
        self.assertIn("espera", manifiesto["siguiente"])
        self.assertIn(
            "Nombre",
            manifiesto["progreso_observable"]["campos_rellenos_visibles"],
        )
        self.assertIn(
            "Certificado academico",
            manifiesto["progreso_observable"]["campos_vacios_visibles"],
        )
        self.assertEqual(
            manifiesto["progreso_observable"]["acciones_finales_visibles"],
            [{"ref": "e4", "rol": "boton", "nombre": "Enviar solicitud"}],
        )

    def test_tras_confirmar_entrega_el_estado_fresco_para_continuar(self):
        with patch.object(relevo.ui, "capturar", return_value=self._captura()):
            manifiesto = relevo.preparar(True, "No envies la solicitud")

        self.assertEqual(manifiesto["estado"], "listo_para_continuar")
        self.assertEqual(manifiesto["contrato"]["limite"], "No envies la solicitud")
        self.assertIn("Continua", manifiesto["siguiente"])

    def test_un_arbol_vacio_no_invita_a_actuar_a_ciegas(self):
        captura = {
            **self._captura(), "arbol": "", "nodos": 0, "vacio": True,
        }
        with patch.object(relevo.ui, "capturar", return_value=captura):
            manifiesto = relevo.preparar(True)

        self.assertEqual(manifiesto["calidad"], "degradada")
        self.assertIn("devices_screenshot", manifiesto["siguiente"])
        self.assertIn("no actues", manifiesto["siguiente"])

    def test_la_actividad_es_efimera_y_no_repite_el_mismo_foco(self):
        observaciones = [
            {
                "instante": 100.0,
                "tipo": "foco",
                "ventana": "Correo",
                "elemento": {"rol": "campo", "nombre": "Destinatario"},
                "_clave": ("Correo", (1,), "Destinatario"),
            },
            {
                "instante": 101.0,
                "tipo": "foco",
                "ventana": "Correo",
                "elemento": {"rol": "campo", "nombre": "Destinatario"},
                "_clave": ("Correo", (1,), "Destinatario"),
            },
            {
                "instante": 102.0,
                "tipo": "foco",
                "ventana": "Correo",
                "elemento": {"rol": "boton", "nombre": "Adjuntar"},
                "_clave": ("Correo", (2,), "Adjuntar"),
            },
        ]
        with patch.object(relevo, "_observacion_actual", side_effect=observaciones):
            relevo.observar_una_vez()
            relevo.observar_una_vez()
            relevo.observar_una_vez()

        recientes = relevo.actividad_reciente(ahora=103.0)
        self.assertEqual([e["elemento"]["nombre"] for e in recientes], [
            "Destinatario", "Adjuntar",
        ])
        self.assertNotIn("instante", recientes[0])


class CamposProtegidos(TestCase):
    def test_windows_no_incluye_el_valor_de_una_contrasena(self):
        propiedades = {
            ui_windows.P_ES_ESCRIBIBLE: True,
            ui_windows.P_ES_PASSWORD: True,
            ui_windows.P_VALOR: "secreto",
            ui_windows.P_TIPO: 50004,
            ui_windows.P_NOMBRE: "Contrasena",
            ui_windows.P_HABILITADO: True,
        }

        with patch.object(
            ui_windows, "_cacheado",
            side_effect=lambda _elemento, propiedad, por_defecto=None: propiedades.get(
                propiedad, por_defecto
            ),
        ):
            nodo = ui_windows._uno(object(), ())

        self.assertIsNone(nodo.valor)
        self.assertIn("protegido", nodo.estado)


class HerramientaDelServidor(TestCase):
    def setUp(self):
        self.usuario = {"id": "u1", "nombre": "Ana"}
        self.nodo = {
            "id": "n1",
            "nombre": "PC",
            "plataforma": "windows",
            "estado": "activo",
            "capacidades": ["relevo.preparar", "ui.batch"],
            "last_seen": 1,
            "created_at": 1,
        }

    def _argumentos(self, **campos):
        modelo = tools.PRIMITIVES["devices.relevo"].input_model
        return modelo.model_validate(campos)

    def test_no_encola_una_foto_del_escritorio_para_mas_tarde(self):
        resultado_nodo = {
            "schema": "vibi.relevo.desktop.v1",
            "estado": "esperando_confirmacion",
            "estado_actual": {"ventana": "Factura"},
        }
        despachar = AsyncMock(return_value={
            "estado": "ok",
            "order_id": "o1",
            "resultado": resultado_nodo,
        })

        async def sin_receta(_usuario, respuesta, _pista):
            return respuesta

        with (
            patch.object(tools, "resolve_device", return_value=self.nodo),
            patch.object(tools.nodes, "dispatch", despachar),
            patch.object(tools, "_con_receta", side_effect=sin_receta),
        ):
            salida = asyncio.run(
                tools._device_relevo(
                    self.usuario,
                    self._argumentos(confirmed=False, boundary="Antes de enviar"),
                )
            )

        self.assertEqual(salida["manifest"]["observacion_id"], "o1")
        despachar.assert_awaited_once_with(
            self.usuario,
            self.nodo,
            "relevo.preparar",
            {"confirmado": False, "limite": "Antes de enviar"},
            queue_if_offline=False,
        )

    def test_un_equipo_apagado_no_se_disfraza_de_relevo_pendiente(self):
        with (
            patch.object(tools, "resolve_device", return_value=self.nodo),
            patch.object(
                tools.nodes, "dispatch", AsyncMock(side_effect=nodes.NodeOffline("apagado"))
            ),
        ):
            with self.assertRaisesRegex(tools.ToolError, "apagado"):
                asyncio.run(
                    tools._device_relevo(self.usuario, self._argumentos())
                )

    def test_se_publica_en_mcp_y_en_la_cabecera_de_antigravity(self):
        self.assertIn("devices.relevo", agy_mcp.tools_publicadas())
        self.assertEqual(
            agy_mcp.id_primitiva("devices_relevo"), "devices.relevo"
        )
        firmas = antigravity_chat.firmas_de_herramientas(
            antigravity_chat.HERRAMIENTAS_DE_CABECERA
        )
        self.assertIn("devices_relevo(device?, confirmed?, boundary?)", firmas)

    def test_el_servidor_clasifica_el_relevo_como_lectura_externa(self):
        self.assertIn("relevo.preparar", nodes.CAPABILITIES)
        self.assertIn("relevo.preparar", nodes.CAPACIDADES_LECTURA)
        self.assertIn("relevo.preparar", nodes.CAPACIDADES_CON_CONTENIDO_AJENO)
