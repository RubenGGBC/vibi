"""Tareas largas dentro de aplicaciones cuyo proceso permanece vivo."""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

from vibi_node import vigilancias as vigilancias_nodo  # noqa: E402

from app import db, tools, vigilancias  # noqa: E402
from app.executors.chat_engine import ChatResult  # noqa: E402


class SondaActividadDelNodo(TestCase):
    def test_usa_el_estado_semantico_de_la_ventana(self):
        encargo = vigilancias_nodo.Encargo(
            id="larga",
            sonda="actividad",
            parametros={"ventana": "Renderizador"},
            intervalo=15,
        )
        with patch.object(
            vigilancias_nodo,
            "_sondear_ventana",
            return_value=("resultado", "Render terminado"),
        ) as sondear:
            resultado = asyncio.run(vigilancias_nodo.sondear(encargo))

        self.assertEqual(resultado, ("resultado", "Render terminado"))
        sondear.assert_called_once_with({"ventana": "Renderizador"})

    def test_la_suscripcion_acepta_actividad(self):
        encargos = vigilancias_nodo.Encargos()
        encargos.reemplazar([
            {
                "id": "larga",
                "sonda": "actividad",
                "parametros": {"ventana": "Editor"},
                "intervalo": 12,
            }
        ])
        self.assertEqual(len(encargos), 1)

    def test_envia_el_estado_inicial_estable_tras_una_reconexion(self):
        encargo = vigilancias_nodo.Encargo(
            id="larga",
            sonda="actividad",
            parametros={"ventana": "Editor"},
            intervalo=1,
        )
        conexion = AsyncMock()

        async def mirar_dos_veces():
            with patch.object(
                vigilancias_nodo,
                "sondear",
                AsyncMock(return_value=("final", "Tarea terminada")),
            ):
                await vigilancias_nodo._una_vuelta(conexion, encargo, 0)
                await vigilancias_nodo._una_vuelta(conexion, encargo, 1)

        asyncio.run(mirar_dos_veces())

        mensaje = json.loads(conexion.send.await_args.args[0])
        self.assertEqual(mensaje["antes"], "")
        self.assertEqual(mensaje["ahora"], "Tarea terminada")


class JuicioDeActividad(TestCase):
    def test_distingue_progreso_intervencion_y_final(self):
        self.assertEqual(
            vigilancias._interpretar_actividad("PROGRESO:"), ("progreso", "")
        )
        self.assertEqual(
            vigilancias._interpretar_actividad("INTERVENCION: Elige un formato"),
            ("intervencion", "Elige un formato"),
        )
        self.assertEqual(
            vigilancias._interpretar_actividad("CUMPLIDO: El render ha terminado"),
            ("cumplido", "El render ha terminado"),
        )

    def test_una_sonda_ordinaria_no_acepta_continuacion_agentica(self):
        for argumentos in (
            {
                "sonda": "proceso", "que_espero": "que termine", "pid": 42,
                "al_terminar": "haz otra cosa",
            },
            {
                "sonda": "web", "que_espero": "que cambie", "app": "Zen",
                "al_terminar": "haz otra cosa",
            },
        ):
            with self.subTest(sonda=argumentos["sonda"]), self.assertRaises(
                tools.InvalidToolArguments
            ):
                tools._parametros_de_sonda(tools.VigilarArguments(**argumentos))

    def test_el_progreso_no_habla_ni_cierra(self):
        vigilancia = self._crear()
        with (
            patch.object(
                vigilancias, "juzgar", AsyncMock(return_value=("progreso", ""))
            ),
            patch.object(vigilancias, "_contar", AsyncMock()) as contar,
        ):
            dicho = asyncio.run(vigilancias.recibir_novedad(
                vigilancia["node_id"],
                {"vigilancia": vigilancia["id"], "ahora": "50 por ciento"},
            ))

        self.assertFalse(dicho)
        contar.assert_not_awaited()
        self.assertEqual(vigilancias.obtener(vigilancia["id"])["estado"], "viva")

    def test_cumplido_deja_la_continuacion_en_cola(self):
        vigilancia = self._crear()
        with (
            patch.object(
                vigilancias,
                "juzgar",
                AsyncMock(return_value=("cumplido", "El render terminó")),
            ),
            patch.object(vigilancias, "sincronizar", AsyncMock()),
            patch.object(vigilancias, "anunciar_estado", AsyncMock()),
            patch.object(vigilancias, "_contar", AsyncMock()),
        ):
            dicho = asyncio.run(vigilancias.recibir_novedad(
                vigilancia["node_id"],
                {"vigilancia": vigilancia["id"], "ahora": "Terminado"},
            ))

        guardada = vigilancias.obtener(vigilancia["id"])
        self.assertTrue(dicho)
        self.assertEqual(guardada["estado"], "cumplida")
        self.assertEqual(guardada["continuacion_estado"], "pendiente")

    def _crear(self) -> dict:
        user_id = str(uuid.uuid4())
        return vigilancias.crear(
            user_id,
            f"node-{uuid.uuid4()}",
            "actividad",
            {"ventana": "Renderizador"},
            "que termine el render",
            continuacion="revisa el archivo generado",
            conversation_id="conversation-1",
        )


class ContinuacionPersistente(TestCase):
    def test_reclama_ejecuta_y_locuta_el_informe(self):
        user = db.get_or_create_user(f"vigilancia-{uuid.uuid4()}")
        conversation = db.get_or_create_active_conversation(user["id"])
        vigilancia = vigilancias.crear(
            user["id"],
            f"node-{uuid.uuid4()}",
            "actividad",
            {"ventana": "Editor"},
            "que termine la refactorización",
            continuacion="ejecuta las pruebas y revisa el diff",
            conversation_id=conversation["id"],
        )
        vigilancias.cerrar(vigilancia["id"], "cumplida", "Terminó")
        reclamada = vigilancias.reclamar_continuacion(vigilancia["id"])

        with (
            patch(
                "app.executors.chat.respond",
                AsyncMock(return_value=ChatResult(response="Pruebas correctas.")),
            ) as responder,
            patch.object(vigilancias.events, "notificar_hablando", AsyncMock()) as hablar,
        ):
            asyncio.run(vigilancias._ejecutar_continuacion(reclamada))

        guardada = vigilancias.obtener(vigilancia["id"])
        self.assertEqual(guardada["continuacion_estado"], "completada")
        self.assertIn("ejecuta las pruebas", responder.await_args.args[1])
        hablar.assert_awaited_once_with(user["id"], "Pruebas correctas.")

    def test_recupera_una_reclamacion_interrumpida(self):
        vigilancia = vigilancias.crear(
            str(uuid.uuid4()),
            f"node-{uuid.uuid4()}",
            "actividad",
            {"ventana": "Editor"},
            "que termine",
            continuacion="verifica el resultado",
        )
        vigilancias.cerrar(vigilancia["id"], "cumplida")
        vigilancias.reclamar_continuacion(vigilancia["id"])

        vigilancias.recuperar_continuaciones_interrumpidas()

        self.assertEqual(
            vigilancias.obtener(vigilancia["id"])["continuacion_estado"],
            "pendiente",
        )
