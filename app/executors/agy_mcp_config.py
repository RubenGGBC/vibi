"""Qué servidores MCP ve `agy`, y con qué credenciales.

Componer esta configuración y escribirla en disco son dos trabajos distintos y
aquí solo se hace el primero. La diferencia importa: con seis servidores en
juego, decidir cuáles entran es donde están las reglas —qué credencial hace
falta, qué se borra cuando no la hay— y conviene poder leerlas sin tenerlas
mezcladas con el manejo del archivo. Escribirlo es cosa de
`antigravity_chat.escribir_configuracion_mcp`.

`agy` admite tres formas de declarar un servidor, y aquí se usan las tres:

- `command`: lo lanza él como proceso hijo. Así va el puente de Vibi, que vive
  donde vive el core.
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
SERVIDOR_VIBI = "vibi"
SERVIDOR_NAVEGADOR = "playwright"
# Corto a propósito: las tools llegan al modelo como `pc_leer`, `pc_ejecutar`,
# y ahí el nombre se lee en cada llamada.
SERVIDOR_SISTEMA = "pc"
SERVIDOR_EXA = "exa"

# Con qué variable de entorno se le cuenta al puente MCP si el servidor del
# ordenador está declarado. El puente es un proceso hijo de `agy` y no ve la
# configuración que lo lanzó, así que lo que decide qué publica tiene que
# viajarle por aquí.
VARIABLE_PC_MCP = "VIBI_PC_MCP"

# Nombres con los que declaramos servidores en el pasado. Siguen aquí porque
# `construir_servidores` solo manda sobre lo que nombra: una entrada que deja
# de aparecer no se borra, se hereda, y el merge la trata como si la hubiera
# puesto el usuario. `morgana` es el nombre viejo de este proyecto y sobrevivió
# al cambio apuntando a `/srv/morgana`, que ya no existe —con sus 28 esquemas
# cacheados en disco, o sea media caja de herramientas duplicada delante del
# modelo—. Al renombrar un servidor hay que dejar el nombre viejo aquí.
# `exa` está aquí por lo mismo aunque nunca cambiara de nombre: `agy` trae
# `search_web` propio, y con Exa declarado y disponible el modelo hizo cinco
# búsquedas nativas seguidas sin tocarlo (traza del 19/08/2026). Era un proceso
# hijo por sesión, dos esquemas más delante del modelo y una clave pagándose,
# para algo que ya venía incluido.
SERVIDORES_HEREDADOS = ("morgana", SERVIDOR_EXA)

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
#
# El navegador cuenta desde que navega con tu propio perfil. El texto de una web
# siempre lo escribió un desconocido, pero antes ese desconocido le hablaba a un
# navegador sin sesiones y lo peor que conseguía era mentirle al modelo. Ahora
# una instrucción colada en una página se ejecutaría dentro de tus cuentas.
SERVIDORES_EXTERNOS = (
    SERVIDOR_EXA,
    SERVIDOR_SISTEMA,
    SERVIDOR_NAVEGADOR,
    *GOOGLE_MCP_URLS,
)


# Capacidades que `agy` ya alcanza por otro camino sobre la misma máquina, y
# que por tanto no se le publican. La primitiva sigue existiendo —la PWA,
# Telegram y el router la llaman— y `agy_mcp.id_primitiva` la sigue
# resolviendo: lo que se quita es el segundo camino delante del modelo.
#
# No es cosmética. En la traza del 19/08/2026, con los dos caminos delante, el
# modelo gastó ocho pasos en averiguar cuál usar —`view_file` de tres esquemas,
# `list_dir` del directorio MCP, `call_mcp_tool pc/info`— antes de tocar la
# pregunta que se le había hecho. Ese turno murió a los 60 s.
#
# El criterio para entrar aquí es estricto: que `pc_*` haga lo mismo sobre la
# misma máquina. `devices.launch_app` y `devices.open_url` NO entran, aunque lo
# parezcan: la primera resuelve un catálogo local en vez de hacer que el modelo
# adivine la ruta del ejecutable, y la segunda abre en el navegador del usuario
# para que mire él, que no es navegar.
# La terminal la alcanza siempre, declaremos `pc` o no: con el servidor va por
# `pc_ejecutar` —que además tiene `pc_lanzar` y `pc_progreso` para lo largo— y
# sin él por su propio `run_command`, que es esa misma máquina.
CUBIERTAS_SIEMPRE = ("devices.shell",)

# Esta, en cambio, solo la cubre `pc_buscar`. Estuvo oculta sin condición y eso
# dejó un agujero al pasar el core a nativo: sin servidor `pc` que declarar, la
# búsqueda por el índice de Windows —482 ms para treinta PDF de todo el disco—
# se volvió inalcanzable, y lo que le quedaba al modelo era recorrer carpetas
# con `run_command`, que en el histórico de este equipo da mediana de 300
# segundos. `grep_search` no la sustituye: busca DENTRO de los archivos de una
# carpeta, no un nombre por todo el disco.
CUBIERTAS_POR_PC = ("devices.files_search",)

# Lo que se poda cuando están las dos vías. Se conserva el nombre porque es el
# que usa la limpieza de esquemas cacheados.
CUBIERTAS_POR_EL_SISTEMA = CUBIERTAS_SIEMPRE + CUBIERTAS_POR_PC


def cubiertas_por_el_sistema(pc_declarado: bool) -> tuple[str, ...]:
    """Las capacidades que NO se le publican porque ya tiene otro camino.

    Ocultar algo solo vale si su sustituto está delante. Ocultarlo sin él no
    es podar: es quitarle la herramienta y no darle ninguna, que es peor que
    el problema que la poda venía a resolver.
    """
    return CUBIERTAS_SIEMPRE + (CUBIERTAS_POR_PC if pc_declarado else ())


# Los nombres con los que una máquina se refiere a sí misma. Si el disco que
# se sirve está en uno de ellos, `agy` corre en esa misma máquina.
HOSTS_LOCALES = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", ""})


def disco_alcanzable_sin_mcp(sistema_url: str) -> bool:
    """¿Llega `agy` al disco del usuario sin que le pongamos un servidor?

    `agy` corre donde corre el core. Mientras eso era un contenedor, sus
    herramientas nativas veían un Linux vacío y `pc_*` era el único puente
    hasta el disco de verdad. Con el core en el ordenador del usuario,
    `run_command` y `view_file` YA son ese disco: declarar el servidor solo
    consigue darle dos caminos para lo mismo, y el modelo se los lee antes de
    elegir —dos pasos de `view_file` sobre `mcp/pc/*.json` medidos el
    19/08/2026, con su propia terminal a mano—.

    La malla no se toca: si el disco que se sirve es el de otra máquina, ahí
    `agy` no llega solo y el servidor sigue haciendo falta.

    Se deduce de la propia URL y no de un ajuste aparte: la URL ya lleva
    dentro la máquina donde está el disco, y así la respuesta no puede
    contradecir a lo que se está declarando.
    """
    candidato = sistema_url.strip().lower()
    if "://" in candidato:
        from urllib.parse import urlsplit  # noqa: PLC0415

        candidato = urlsplit(candidato).hostname or ""
    return candidato in HOSTS_LOCALES


def servidores_externos(
    settings, sistema: bool = False, navegador: bool = False
) -> tuple[str, ...]:
    """Cuáles de los que traen texto ajeno están declarados de verdad.

    Lo usan dos sitios que tienen que contar lo mismo: las reglas del prompt,
    que no deben prometer una capacidad que no está, y el marcado de
    procedencia, que no debe vigilar un servidor que nadie declaró.

    El del ordenador y el del navegador van aparte porque no dependen de una
    credencial sino de que haya una máquina conectada que los sirva, y eso solo
    se sabe al abrir la sesión: por eso llegan como argumento en vez de
    deducirse de `settings`.
    """
    declarados = [
        nombre
        for nombre, definicion in _externos(settings).items()
        if definicion is not None
    ]
    if sistema:
        declarados.insert(0, SERVIDOR_SISTEMA)
    if navegador:
        declarados.insert(0, SERVIDOR_NAVEGADOR)
    return tuple(declarados)


def _externos(settings) -> dict[str, dict | None]:
    """Los servidores de terceros, y `None` para el que no toca declarar."""
    # Sin Exa: la búsqueda web la pone `agy` con su `search_web` nativo. Se
    # declara a `None` en vez de omitirse para que la entrada de quien ya la
    # tuviera se borre, junto con sus esquemas cacheados.
    definiciones: dict[str, dict | None] = {SERVIDOR_EXA: None}

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


def _entrada(cap: dict) -> dict | None:
    """La forma en que se declara este servidor, según cómo se llegue a él.

    Un remoto se declara con su URL. Uno local necesita comando y argumentos,
    y eso no se sabe hasta que se instala: hasta entonces no se declara, que
    es más honesto que declarar una entrada rota.
    """
    if cap["transporte"] == "remoto" and cap["endpoint"]:
        return {"url": cap["endpoint"]}
    return None


def del_perfil(user_id: str) -> dict[str, dict | None]:
    """Los servidores que el perfil de este usuario justifica.

    Los que han bajado de nivel salen a `None` y no ausentes: aquí una entrada
    que falta se queda como estuviera, y un servidor retirado del perfil que
    sobrevive en la configuración es justo el caso que hace a `agy` gastar el
    arranque descubriendo que ya no se puede entrar ahí.
    """
    from .. import perfil, perfil_activador  # noqa: PLC0415 - perezoso

    capacidades = perfil.capacidades_de(user_id, "mcp")
    if not capacidades:
        return {}
    conf = perfil_activador.decidir(
        perfil.afirmaciones_de(user_id), perfil.capacidades_de(user_id)
    )
    activos = set(conf.mcp)
    return {
        cap["referencia"]: (_entrada(cap) if cap["referencia"] in activos else None)
        for cap in capacidades
    }


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
    # Se decide una vez y la usan los dos sitios que dependen de ella: la
    # entrada del servidor y lo que el puente publica. Calculada dos veces
    # acaba divergiendo, y el resultado es justo el que hay que evitar —una
    # capacidad podada porque «ya la cubre `pc`» sin que `pc` esté—.
    pc_declarado = bool(sistema_url) and not disco_alcanzable_sin_mcp(sistema_url)
    # Base y no fusión final: el perfil va primero para que, si algún día una
    # referencia aprobada coincidiera de nombre con uno de los que ya
    # gestionamos, sea la entrada gestionada la que sobreviva. Lo contrario
    # dejaría a un usuario pisar sin querer `vibi`, `pc` o cualquier Google
    # MCP con una capacidad aprobada del mismo nombre.
    servidores: dict[str, dict | None] = del_perfil(user_id)
    servidores.update({
        SERVIDOR_VIBI: {
            "command": sys.executable,
            "args": [str(aqui.parent / "agy_mcp.py")],
            "env": {
                # El puente corre en otro proceso y no ve esta decisión, pero
                # de ella depende qué publica: lo que `pc_*` cubre se poda, y
                # lo que no, no (ver `cubiertas_por_el_sistema`).
                VARIABLE_PC_MCP: "1" if pc_declarado else "",
                # El puente no ejecuta nada por su cuenta: se lo pide a Vibi
                # en su nombre. Le damos un token en vez del secreto para
                # firmarlo, que no tiene por qué salir de aquí.
                "VIBI_TOKEN": auth.create_access_token(user_id),
                # Localhost y no la URL pública: el puente vive en este mismo
                # contenedor, y salir a la tailnet para volver a entrar sería
                # dar un rodeo que además puede no tener camino de vuelta.
                "VIBI_URL": "http://127.0.0.1:8000",
                # `agy` lanza el servidor desde su propio directorio, así que
                # hay que decirle dónde vive el paquete o no se importaría.
                "VIBI_ROOT": str(aqui.parents[2]),
            },
        },
        SERVIDOR_NAVEGADOR: {"serverUrl": playwright_url} if playwright_url else None,
        # El disco y el intérprete del ordenador del usuario, y solo cuando
        # `agy` no llegue ya por su cuenta (ver `disco_alcanzable_sin_mcp`). La
        # URL ya trae dentro el secreto que el agente puso en la ruta, así que
        # aquí no hay nada más que declarar: quien no la tenga entera no pasa
        # del 404.
        SERVIDOR_SISTEMA: {"serverUrl": sistema_url} if pc_declarado else None,
    })
    servidores.update(_externos(settings))
    # Explícitos a `None` para que el volcado los borre. Van al final y sin
    # pisar: si alguna vez se reutilizara un nombre heredado, manda el vivo.
    for nombre in SERVIDORES_HEREDADOS:
        servidores.setdefault(nombre, None)
    return servidores
