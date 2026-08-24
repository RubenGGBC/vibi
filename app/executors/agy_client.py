"""Cliente del language server que `agy` levanta en localhost.

La CLI de Antigravity no es un programa monolítico: arranca dentro de sí un
servidor y le habla por Connect RPC. Ese servidor acepta JSON plano y no pide
credenciales, así que Vibi puede usarlo igual que lo usa la propia CLI, sin
parsear pantallas ni el SQLite interno.

Es formato interno de Google y `agy` se actualiza solo, así que esto puede
romperse con una versión nueva. Cuando pase, las llamadas devolverán un error
legible y el turno se irá a Claude.
"""
from __future__ import annotations

import json
import logging
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import Iterator

log = logging.getLogger("vibi.agy")

SERVICE = "exa.language_server_pb.LanguageServerService"

STEP_PLANNER_RESPONSE = "CORTEX_STEP_TYPE_PLANNER_RESPONSE"
# El paso que ejecuta algo fuera de `agy`. Se distingue del resto de
# herramientas porque su duración no la manda el modelo: la manda el comando,
# y un comando de desarrollo tarda minutos con toda normalidad.
STEP_RUN_COMMAND = "CORTEX_STEP_TYPE_RUN_COMMAND"
STATUS_DONE = "CORTEX_STEP_STATUS_DONE"

# El estado del *run*, que es otra cosa que el estado de un paso: dice si el
# agente sigue en marcha o ya está esperando a que le hablen. Es la señal de
# fin de turno de verdad, y hasta el 24/08/2026 no se miraba.
CASCADE_IDLE = "CASCADE_RUN_STATUS_IDLE"
# Dónde lo cuenta, en orden de preferencia. `fullyIdle` es el resumen —solo
# viene cuando ha terminado del todo, porque proto3 no serializa los `false`—
# y los otros tres son el estado de cada capa del ejecutor.
CAMPOS_DEL_RUN = ("executorLoopStatus", "executableStatus", "status")

# Los pasos que forman el andamiaje del turno. Todo lo demás que aparezca es
# una herramienta: `LIST_DIRECTORY`, `SEARCH_WEB` y las que vengan, que no hay
# lista cerrada y no conviene inventarla.
PASOS_DE_ANDAMIAJE = frozenset({
    STEP_PLANNER_RESPONSE,
    "CORTEX_STEP_TYPE_USER_INPUT",
    "CORTEX_STEP_TYPE_CONVERSATION_HISTORY",
    "CORTEX_STEP_TYPE_CHECKPOINT",
    # `GENERIC` tampoco es una herramienta, y colarse aquí le costaba a Vibi
    # el turno entero: llega en `RUNNING` y nadie manda nunca su `DONE`, así
    # que `_hay_herramientas_a_medias` decía que sí para siempre y el turno no
    # cerraba jamás. La respuesta estaba escrita y cerrada, pero Vibi seguía
    # esperando hasta agotar los 60 s de silencio y se la pasaba a Claude.
    #
    # Comprobado contra el `agy` real el 19/08/2026 con un «echo hola»: el
    # comando se ejecutó, el paso de respuesta quedó DONE con «hola» dentro, y
    # el turno cayó igualmente. Son 20 de las 47 caídas reales, y ninguna era
    # de Google como parecía por los `streamGenerateContent` del log.
    #
    # El resto de tipos que existen sí nombran una acción —`RUN_COMMAND`,
    # `VIEW_FILE`, `SEARCH_WEB`, `BROWSER_CLICK_ELEMENT`—: los 55 que declara
    # el binario se leen con
    # `strings agy.exe | grep -oE "CORTEX_STEP_TYPE_[A-Z_]+"`.
    "CORTEX_STEP_TYPE_GENERIC",
})
ESTADOS_EN_CURSO = frozenset({
    "CORTEX_STEP_STATUS_PENDING",
    "CORTEX_STEP_STATUS_RUNNING",
})


# Lo que cabe de un comando o una consulta en una línea de la ventana. Un
# `Get-ChildItem -Recurse` con veinte filtros ocupa mil caracteres y no aporta
# nada después del primer centenar.
MAX_DETALLE = 300


@dataclass(frozen=True)
class Paso:
    """Una cosa concreta que `agy` está haciendo, para poder verla.

    `detalle` es lo que distingue mirar de adivinar: sin él solo se sabe que
    hubo «un comando», y con él se lee el comando. `nombre` viene sin el
    prefijo `CORTEX_STEP_TYPE_`, que ocupa media línea y no dice nada.
    """

    tipo: str
    estado: str
    detalle: str = ""

    @property
    def nombre(self) -> str:
        return nombre_de_paso(self.tipo)

    @property
    def en_curso(self) -> bool:
        return self.estado in ESTADOS_EN_CURSO


def nombre_de_paso(tipo: str) -> str:
    """El tipo sin el prefijo que llevan todos, para poder leerlo."""
    return tipo.removeprefix("CORTEX_STEP_TYPE_").lower() if tipo.startswith(
        "CORTEX_STEP_TYPE_"
    ) else tipo


# De dónde sacar el detalle de cada tipo de paso, en orden de preferencia. No
# es una lista cerrada ni pretende serlo: `agy` estrena tipos sin avisar, y para
# los que no estén aquí se rebusca el primer texto con pinta de serlo. Salir
# aproximado vale más que salir en blanco.
CAMPOS_CON_DETALLE = (
    "commandLine",
    "query",
    "absolutePath",
    "directoryPath",
    "path",
    "url",
    "toolName",
    "searchTerm",
    # El último: es el más genérico y solo debe ganar si no hay nada mejor.
    "name",
)


# Campos que nunca son el detalle aunque sean texto: llevan la respuesta entera
# de la herramienta, que en una línea de la ventana no es información sino
# ruido, o identificadores que no significan nada para quien mira.
CAMPOS_QUE_NO_SON_DETALLE = frozenset({"resultstring", "id", "callid", "argumentsjson"})


def _aplanar(valor: dict, profundidad: int = 2) -> dict[str, str]:
    """Los textos de un objeto, mirando también un par de niveles adentro.

    Hace falta porque `agy` anida lo que importa: el nombre de una herramienta
    MCP viaja en `mcpTool.toolCall.name`, no al lado del servidor. Mirando solo
    el primer nivel se cogía `serverName` y la ventana ponía «vibi» a secas,
    que no distingue apagar la música de leerte el correo.
    """
    plano: dict[str, str] = {}
    for clave, dentro in valor.items():
        minuscula = clave.lower()
        if minuscula in CAMPOS_QUE_NO_SON_DETALLE:
            continue
        if isinstance(dentro, str):
            plano.setdefault(minuscula, dentro)
        elif isinstance(dentro, dict) and profundidad > 0:
            for anidada, texto in _aplanar(dentro, profundidad - 1).items():
                plano.setdefault(anidada, texto)
    return plano


def _detalle_del_paso(paso: dict) -> str:
    """Lo que se lee de un paso: el comando, la consulta, el archivo…"""
    for clave, valor in paso.items():
        if clave in ("type", "status", "metadata") or not isinstance(valor, dict):
            continue
        # Las claves llegan en camelCase y no siempre con el mismo nombre, así
        # que se comparan en minúsculas y sin distinguir.
        plano = _aplanar(valor)
        servidor = plano.get("servername", "")
        for candidato in CAMPOS_CON_DETALLE:
            encontrado = plano.get(candidato.lower())
            if encontrado:
                if candidato in ("toolName", "name") and servidor:
                    return f"{servidor}: {encontrado}"[:MAX_DETALLE]
                return encontrado[:MAX_DETALLE]
        # Nada conocido: vale el primer texto que parezca contenido y no un id.
        for nombre, texto in plano.items():
            if len(texto) > 2 and nombre != "servername":
                return texto[:MAX_DETALLE]
        if servidor:
            return servidor[:MAX_DETALLE]
    return ""


@dataclass(frozen=True)
class Update:
    """Lo único que a Vibi le interesa de una actualización del stream."""

    text: str | None = None
    done: bool = False
    # Herramientas nombradas en este mensaje, con el estado en que van. Sin
    # esto no se puede saber si un `done` cierra el turno o solo cierra la
    # frase con la que el modelo anuncia que va a mirar algo.
    herramientas: tuple[tuple[str, str], ...] = ()
    # Una trayectoria puede avanzar sin producir texto mientras ejecuta una
    # herramienta. Ese movimiento cuenta como señal de vida para el turno.
    activity: bool = False
    tools_running: bool = False
    # Lo mismo que `herramientas` pero con el detalle dentro, para poder
    # enseñar qué está haciendo y no solo que está haciendo algo.
    pasos: tuple[Paso, ...] = ()
    # Si el agente sigue trabajando, según él mismo. `None` cuando esta
    # actualización no lo dice, que no es lo mismo que decir que no.
    trabajando: bool | None = None


class AgyError(RuntimeError):
    """El language server no contestó lo que se esperaba."""


class AgyClient:
    """Habla con el language server de una instancia concreta de `agy`."""

    def __init__(self, port: int, timeout: float = 30.0) -> None:
        self.port = port
        self.timeout = timeout

    def _url(self, method: str) -> str:
        # 127.0.0.1 y no "localhost": en Windows resolver el nombre prueba
        # primero IPv6 y se come un timeout en cada llamada.
        return f"http://127.0.0.1:{self.port}/{SERVICE}/{method}"

    def _post(self, method: str, payload: dict) -> dict:
        request = urllib.request.Request(
            self._url(method),
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            detalle = error.read().decode("utf-8", "replace")[:300]
            raise AgyError(f"{method} devolvió {error.code}: {detalle}") from error
        except Exception as error:
            raise AgyError(f"{method} no respondió: {error}") from error

    def conversations(self) -> list[str]:
        """Los identificadores de las conversaciones que `agy` tiene abiertas."""
        data = self._post("GetAllCascadeTrajectories", {})
        return list((data.get("trajectorySummaries") or {}).keys())

    def stop(self, cascade_id: str) -> None:
        """Corta el turno en curso."""
        self._post("ForceStopCascadeTree", {"conversationId": cascade_id})

    def user_input_count(self, cascade_id: str) -> int:
        """Cuántos turnos del usuario ha registrado esta conversación."""
        data = self._post(
            "GetCascadeTrajectorySteps",
            {"cascadeId": cascade_id, "conversationId": cascade_id},
        )
        return sum(
            step.get("type") == "CORTEX_STEP_TYPE_USER_INPUT"
            for step in data.get("steps") or []
        )

    def stream_updates(
        self, cascade_id: str, timeout: float = 300.0, skip_text: str = ""
    ) -> Iterator[Update]:
        """Sigue el turno según lo va escribiendo el modelo.

        La conexión se abre aquí mismo, no al empezar a leer: quien llama
        teclea el turno justo después, y si el stream no estuviera ya
        escuchando se perdería el principio de la respuesta.

        `skip_text` es la respuesta del turno anterior. Hace falta porque al
        abrir el stream el servidor vuelca el estado actual, que la trae ya
        marcada como terminada: sin descartarla, el turno se cerraría antes de
        empezar repitiendo lo que Vibi ya había dicho.

        Termina cuando el paso de respuesta pasa a `DONE`, que es la señal
        buena: antes había que adivinarlo por el silencio en pantalla.
        """
        return self._iter_updates(
            self._open_stream(cascade_id, timeout), skip_text
        )

    def _open_stream(self, cascade_id: str, timeout: float):
        payload = json.dumps(
            {"cascadeId": cascade_id, "conversationId": cascade_id}
        ).encode()
        # Connect exige el sobre también en la petición.
        envelope = b"\x00" + struct.pack(">I", len(payload)) + payload
        request = urllib.request.Request(
            self._url("StreamAgentStateUpdates"),
            data=envelope,
            headers={
                "content-type": "application/connect+json",
                "connect-protocol-version": "1",
            },
        )
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            detalle = error.read().decode("utf-8", "replace")[:300]
            raise AgyError(f"el stream devolvió {error.code}: {detalle}") from error
        except Exception as error:
            raise AgyError(f"no se pudo abrir el stream: {error}") from error

    def _iter_updates(self, response, skip_text: str = "") -> Iterator[Update]:
        empezado = False
        # Comparado sin espacios de los bordes: la respuesta anterior se
        # guarda recortada y el stream no recorta, así que una respuesta que
        # terminara en salto de línea no se reconocía a sí misma. El eco se
        # colaba como respuesta buena y, al venir ya cerrado, cerraba el turno
        # al instante — y desde ahí la conversación entera iba un turno por
        # detrás, contestando siempre a la pregunta anterior.
        anterior = skip_text.strip()
        # Qué herramienta va por dónde. Un `done` en el paso de respuesta no
        # cierra el turno si hay alguna a medias: el modelo anuncia en voz alta
        # que va a mirar algo, cierra esa frase, ejecuta la herramienta y
        # sigue escribiendo después. Cerrar en ese primer `done` dejaba el
        # turno en «deja que lo mire» y mandaba la respuesta buena al turno
        # siguiente, con lo que la conversación entera quedaba desfasada.
        #
        # Esto solo tapa el hueco cuando la herramienta ya se había anunciado,
        # y es una carrera que `gemini-3.5-flash-low` pierde casi siempre:
        # escribe el preámbulo, lo cierra, y **después** pide la herramienta.
        # En ese instante no hay ninguna a medias porque todavía no existe.
        # Por eso manda `trabajando`, que es lo que dice el agente de sí mismo.
        estado_herramientas: dict[str, str] = {}
        # Lo último que el agente dijo de sí mismo. Se conserva entre mensajes
        # porque los deltas de texto no repiten el estado del run.
        trabajando: bool | None = None
        # Si el último trozo de respuesta venía cerrado.
        respuesta_cerrada = False
        with response:
            for raw in read_envelopes(response):
                update = read_update(raw)
                if update.trabajando is not None:
                    trabajando = update.trabajando
                estado_herramientas.update(update.herramientas)
                update = replace(
                    update,
                    tools_running=_hay_herramientas_a_medias(
                        estado_herramientas
                    ),
                )
                if update.text is None:
                    if update.activity:
                        yield update
                    # Sin texto no hay nada que cerrar por su cuenta, pero este
                    # mensaje puede traer la señal de fin: el paso a IDLE llega
                    # a veces suelto, después del último trozo de respuesta.
                    # Saltándoselo, el turno se quedaba abierto hasta agotar el
                    # silencio aunque el agente ya hubiera terminado.
                    if _turno_cerrado(
                        respuesta_cerrada,
                        estado_herramientas,
                        trabajando,
                        exigir_senal=True,
                    ):
                        return
                    continue
                if not empezado and anterior and update.text.strip() == anterior and update.done:
                    # El eco del turno anterior, no el principio de este.
                    #
                    # Lo que los distingue es el `done`, no el texto: el eco
                    # llega con su paso ya cerrado, mientras que la respuesta
                    # nueva siempre empieza abierta, aunque sea de una palabra
                    # —comprobado contra el `agy` real: hasta un «hecho» pasa
                    # por GENERATING antes de cerrarse—. Comparando solo el
                    # texto, contestar dos veces lo mismo descartaba también la
                    # respuesta buena y el turno no cerraba nunca.
                    #
                    # Y hay que seguir descartando mientras coincida, no solo
                    # el primero: el volcado inicial puede llegar repartido en
                    # varios mensajes, y dejar pasar el segundo cierra el turno
                    # con la respuesta anterior. Eso desfasa la conversación
                    # entera un turno, que es mucho peor que esperar de más.
                    continue
                empezado = True
                # Si el modelo vuelve a escribir después de un `done`, el turno
                # deja de estar cerrado: manda siempre el último trozo.
                respuesta_cerrada = update.done
                yield update
                if _turno_cerrado(respuesta_cerrada, estado_herramientas, trabajando):
                    return


def _turno_cerrado(
    respuesta_cerrada: bool,
    estado_herramientas: dict[str, str],
    trabajando: bool | None,
    exigir_senal: bool = False,
) -> bool:
    """¿Se puede dar el turno por acabado?

    Lo básico siempre: el modelo cerró su respuesta y no queda ninguna
    herramienta a medias. `trabajando` es el desempate, y vale por los dos
    lados —veta el cierre cuando el agente dice seguir en marcha, y lo permite
    cuando dice haber acabado—, pero `None` significa que no lo ha dicho.

    `exigir_senal` es para cuando se pregunta desde un mensaje que no trae
    respuesta. Ahí no basta con no saberlo: una herramienta que termina no
    cierra el turno, porque lo normal es que el modelo escriba después. Solo
    un «he terminado» explícito cuenta.
    """
    if not respuesta_cerrada or _hay_herramientas_a_medias(estado_herramientas):
        return False
    if exigir_senal:
        return trabajando is False
    return not trabajando


def _hay_herramientas_a_medias(estado: dict[str, str]) -> bool:
    """¿Queda alguna herramienta sin terminar en este turno?

    Solo cuentan las herramientas, no los pasos de andamiaje. El `CHECKPOINT`
    queda fuera a propósito: aparece también después de la última respuesta, y
    esperarlo dejaría el turno abierto para siempre.
    """
    return any(valor in ESTADOS_EN_CURSO for valor in estado.values())


class TurnText:
    """Lleva la cuenta de lo que ya se ha dicho en el turno.

    El stream reenvía la respuesta entera cada vez que crece, así que hay que
    quedarse solo con la parte nueva; si no, la cara locutaría lo mismo una y
    otra vez.
    """

    def __init__(self) -> None:
        self.full = ""

    def advance(self, text: str) -> str | None:
        """Lo que hay que decir de nuevo, o None si no hay nada."""
        if text == self.full:
            return None
        if text.startswith(self.full):
            nuevo = text[len(self.full) :]
        else:
            # El modelo reescribió lo anterior: no se puede recortar por delante.
            nuevo = text
        self.full = text
        return nuevo or None


def _steps(update: dict) -> list[dict]:
    trajectory = (update.get("update") or {}).get("mainTrajectoryUpdate") or {}
    return (trajectory.get("stepsUpdate") or {}).get("steps") or []


def sigue_trabajando(update: dict) -> bool | None:
    """¿Dice esta actualización que el agente aún no ha acabado el turno?

    Devuelve `None` cuando no lo dice, y eso importa: significa «no lo sé», no
    «ha terminado». Un `agy` que no mandara este estado dejaría el turno
    abierto hasta agotar el silencio si se tomara la ausencia por un no.
    """
    cuerpo = update.get("update") or {}
    # `fullyIdle` solo aparece cuando es cierto: proto3 se come los `false`.
    if cuerpo.get("fullyIdle"):
        return False
    for clave in CAMPOS_DEL_RUN:
        estado = cuerpo.get(clave)
        if estado:
            return estado != CASCADE_IDLE
    return None


def read_update(update: dict) -> Update:
    """Traduce una actualización cruda a texto, herramientas y fin de turno.

    El servidor manda muchas que no son de la respuesta (metadatos del
    ejecutor, del generador, del proyecto). Todas esas se ignoran.
    """
    steps = _steps(update)
    trabajando = sigue_trabajando(update)
    del_trabajo = [
        step
        for step in steps
        if step.get("type") and step.get("type") not in PASOS_DE_ANDAMIAJE
    ]
    herramientas = tuple(
        (step.get("type") or "", step.get("status") or "") for step in del_trabajo
    )
    pasos = tuple(
        Paso(
            tipo=step.get("type") or "",
            estado=step.get("status") or "",
            detalle=_detalle_del_paso(step),
        )
        for step in del_trabajo
    )
    # De atrás hacia delante: al abrir el stream, el estado que vuelca trae
    # todos los turnos de la conversación, y el que interesa es el último.
    for step in reversed(steps):
        if step.get("type") != STEP_PLANNER_RESPONSE:
            continue
        response = step.get("plannerResponse") or {}
        # Mientras escribe llega en `modifiedResponse`; al cerrar, en `response`.
        text = response.get("modifiedResponse") or response.get("response")
        if text:
            return Update(
                text=text,
                done=step.get("status") == STATUS_DONE,
                herramientas=herramientas,
                activity=bool(steps),
                pasos=pasos,
                trabajando=trabajando,
            )
    return Update(
        herramientas=herramientas,
        activity=bool(steps),
        pasos=pasos,
        trabajando=trabajando,
    )


def read_envelopes(stream) -> Iterator[dict]:
    """Va devolviendo los mensajes de un server-stream de Connect.

    Cada uno viene precedido de un byte de banderas y cuatro de longitud, así
    que no vale con leer líneas: hay que respetar la cabecera.
    """
    while True:
        header = stream.read(5)
        if len(header) < 5:
            return
        length = struct.unpack(">I", header[1:5])[0]
        payload = b""
        while len(payload) < length:
            chunk = stream.read(length - len(payload))
            if not chunk:
                return
            payload += chunk
        try:
            yield json.loads(payload or b"{}")
        except json.JSONDecodeError:
            return
