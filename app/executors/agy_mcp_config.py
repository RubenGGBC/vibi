"""Qué servidores MCP ve `agy`, y con qué credenciales.

Componer esta configuración y escribirla en disco son dos trabajos distintos y
aquí solo se hace el primero. La diferencia importa: con seis servidores en
juego, decidir cuáles entran es donde están las reglas —qué credencial hace
falta, qué se borra cuando no la hay— y conviene poder leerlas sin tenerlas
mezcladas con el manejo del archivo. Escribirlo es cosa de
`antigravity_chat.escribir_configuracion_mcp`.

`agy` admite tres formas de declarar un servidor, y aquí se usan las tres:

- `command`: lo lanza él como proceso hijo. Así van el puente de Morgana y Exa,
  que viven en este contenedor.
- `serverUrl`: ya está escuchando en algún sitio. Así va el navegador, que
  corre en el ordenador del usuario.
- `serverUrl` + `oauth`: además hay que identificarse. Así van los de Google,
  que son remotos y suyos.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Con qué nombre ve `agy` cada servidor. No son etiquetas libres: sus tools
# llegan al modelo prefijadas con esto, así que cambiar uno obliga a cambiar
# también lo que digan las reglas del prompt.
SERVIDOR_MORGANA = "morgana"
SERVIDOR_NAVEGADOR = "playwright"
# Corto a propósito: las tools llegan al modelo como `pc_leer`, `pc_ejecutar`,
# y ahí el nombre se lee en cada llamada.
SERVIDOR_SISTEMA = "pc"
SERVIDOR_EXA = "exa"

# Los MCP oficiales de Google Workspace, uno por producto. Cada uno necesita su
# API y su «MCP API» habilitadas en el proyecto de Google Cloud del usuario.
GOOGLE_MCP_URLS = {
    "gmail": "https://gmailmcp.googleapis.com/mcp/v1",
    "drive": "https://drivemcp.googleapis.com/mcp/v1",
    "calendar": "https://calendarmcp.googleapis.com/mcp/v1",
}

# Servidores cuyo contenido no lo escribes tú. Lo que devuelven entra en el
# contexto como texto de un desconocido —un correo, una web, un documento
# compartido—, así que marcan procedencia en `app/taint.py`.
#
# El del ordenador cuenta, y no es evidente: son archivos «tuyos». Pero un PDF
# que te descargaste, el README de un repo que clonaste o la salida de un
# programa de terceros los escribió otro, y entran por ahí igual que un correo.
SERVIDORES_EXTERNOS = (SERVIDOR_EXA, SERVIDOR_SISTEMA, *GOOGLE_MCP_URLS)


def servidores_externos(settings, sistema: bool = False) -> tuple[str, ...]:
    """Cuáles de los que traen texto ajeno están declarados de verdad.

    Lo usan dos sitios que tienen que contar lo mismo: las reglas del prompt,
    que no deben prometer una capacidad que no está, y el marcado de
    procedencia, que no debe vigilar un servidor que nadie declaró.

    El del ordenador va aparte porque no depende de una credencial sino de que
    haya una máquina conectada que lo sirva, y eso solo se sabe al abrir la
    sesión: por eso llega como argumento en vez de deducirse de `settings`.
    """
    declarados = [
        nombre
        for nombre, definicion in _externos(settings).items()
        if definicion is not None
    ]
    if sistema:
        declarados.insert(0, SERVIDOR_SISTEMA)
    return tuple(declarados)


def _externos(settings) -> dict[str, dict | None]:
    """Los servidores de terceros, y `None` para el que no toca declarar."""
    exa = None
    if settings.exa_api_key:
        exa = {
            "command": "npx",
            # `--yes` porque la primera vez hay que bajarse el paquete y nadie
            # va a estar delante para confirmarlo.
            "args": ["--yes", "exa-mcp-server"],
            # La clave va aquí y no en la URL. Exa acepta las dos formas, pero
            # en la query string acabaría en los logs de cualquier proxy por el
            # que pase y en el propio archivo de configuración.
            "env": {"EXA_API_KEY": settings.exa_api_key},
        }

    definiciones: dict[str, dict | None] = {SERVIDOR_EXA: exa}

    # Sin cliente OAuth no hay forma de entrar, así que declararlos solo
    # conseguiría que `agy` gastara el arranque en servidores que van a
    # rechazarle. Con credenciales, entran los que pida la lista.
    pedidos = {
        nombre.strip().lower()
        for nombre in settings.google_mcp_servers.split(",")
        if nombre.strip()
    }
    tiene_cliente = bool(
        settings.google_mcp_client_id and settings.google_mcp_client_secret
    )
    for nombre, url in GOOGLE_MCP_URLS.items():
        definiciones[nombre] = (
            {
                "serverUrl": url,
                "oauth": {
                    "clientId": settings.google_mcp_client_id,
                    "clientSecret": settings.google_mcp_client_secret,
                },
            }
            if tiene_cliente and nombre in pedidos
            else None
        )
    return definiciones


def construir_servidores(
    user_id: str, playwright_url: str, settings, sistema_url: str = ""
) -> dict[str, dict | None]:
    """Todos los servidores que gestionamos, listos para volcar.

    Un valor a `None` significa «borra esta entrada», no «déjala como esté».
    Da igual el motivo —el navegador no llegó a abrirse, te has quedado sin
    clave de Exa, has quitado Gmail de la lista—: una entrada que sobrevive a
    su credencial apunta a un sitio donde ya no se puede entrar, y `agy` gasta
    el arranque entero descubriéndolo.

    Lo que el usuario tenga declarado por su cuenta no aparece aquí y por eso
    no se toca.
    """
    from .. import auth  # noqa: PLC0415 - perezoso para no cerrar un ciclo

    aqui = Path(__file__).resolve()
    servidores: dict[str, dict | None] = {
        SERVIDOR_MORGANA: {
            "command": sys.executable,
            "args": [str(aqui.parent / "agy_mcp.py")],
            "env": {
                # El puente no ejecuta nada por su cuenta: se lo pide a Morgana
                # en su nombre. Le damos un token en vez del secreto para
                # firmarlo, que no tiene por qué salir de aquí.
                "MORGANA_TOKEN": auth.create_access_token(user_id),
                # Localhost y no la URL pública: el puente vive en este mismo
                # contenedor, y salir a la tailnet para volver a entrar sería
                # dar un rodeo que además puede no tener camino de vuelta.
                "MORGANA_URL": "http://127.0.0.1:8000",
                # `agy` lanza el servidor desde su propio directorio, así que
                # hay que decirle dónde vive el paquete o no se importaría.
                "MORGANA_ROOT": str(aqui.parents[2]),
            },
        },
        SERVIDOR_NAVEGADOR: {"serverUrl": playwright_url} if playwright_url else None,
        # El disco y el intérprete del ordenador del usuario. La URL ya trae
        # dentro el secreto que el agente puso en la ruta, así que aquí no hay
        # nada más que declarar: quien no la tenga entera no pasa del 404.
        SERVIDOR_SISTEMA: {"serverUrl": sistema_url} if sistema_url else None,
    }
    servidores.update(_externos(settings))
    return servidores
