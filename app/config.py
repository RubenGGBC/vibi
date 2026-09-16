"""Configuración central de Vibi.

Todo sale de variables de entorno (.env). Nada hardcodeado,
para que migrar de máquina sea copiar el .env y listo.
"""
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


MANAGED_UPLOADS_DIRECTORY = "Archivos subidos"


def resolve_vibi_db_path(current: Path, legacy: Path) -> Path:
    """Adopta la base anterior solo cuando todavía no existe la canónica."""
    if current.exists() or not legacy.exists():
        return current
    current.parent.mkdir(parents=True, exist_ok=True)
    try:
        legacy.replace(current)
    except OSError:
        # Poder seguir leyendo los datos vale más que imponer el nombre nuevo
        # cuando el sistema no permite mover el archivo.
        return legacy
    return current


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Identidad ---
    app_name: str = "Vibi"

    # --- Vía rápida (Groq) ---
    groq_api_key: str = ""
    # Groq retiró `llama-3.3-70b-versatile` y desde entonces devolvía un 404
    # por cada aviso, que salía leído tal cual. Este razona antes de contestar:
    # quien lo llame tiene que pasarle `ai_providers.opciones_groq`.
    groq_model: str = "openai/gpt-oss-120b"
    groq_web_search_enabled: bool = True
    groq_search_model: str = "groq/compound-mini"
    groq_task_context_tokens: int = 200
    groq_recent_context_tokens: int = 4_000
    groq_speech_model: str = "whisper-large-v3-turbo"
    voice_max_audio_bytes: int = 5_000_000

    # --- Síntesis de voz (edge-tts) ---
    # Voces neuronales de Microsoft, sin API key ni coste. Si falla, el
    # navegador locuta con speechSynthesis: Vibi nunca se queda muda.
    tts_enabled: bool = True
    tts_voice: str = "es-ES-ElviraNeural"
    # Debe coincidir con MAX_CHUNK_CHARS en frontend/src/lib/voice.ts.
    tts_max_chars: int = 600

    # --- Vía agéntica (Claude Agent SDK) ---
    # auto: usa API key si existe; si no, el login persistido de Claude Code.
    # api: exige ANTHROPIC_API_KEY. subscription: ignora la key y usa Claude Pro/Max.
    claude_auth_mode: Literal["auto", "api", "subscription"] = "auto"
    anthropic_api_key: str = ""

    # --- Vía rápida alternativa (Antigravity / Gemini) ---
    # La CLI `agy` del usuario, mantenida viva en un pseudoterminal. Con el
    # proceso ya abierto un turno tarda ~0,6 s; arrancarlo cuesta ~10 s, y por
    # eso las sesiones se reutilizan en lugar de abrirse por mensaje.
    # Vacío = el `agy` que esté en el PATH.
    agy_binary: str = ""
    # Vacío = el modelo que el usuario tenga elegido en su propia CLI.
    antigravity_model: str = ""
    # Cuánto razona antes de contestar (low|medium|high). Ojo: el sufijo del
    # modelo —`gemini-3.6-flash-low`— es otra palanca distinta y también
    # cuenta. Vacío = lo que traiga la CLI por defecto.
    antigravity_effort: str = "high"
    # Cuánto aguanta un `agy` sin usarse antes de que lo cierren. Alto a
    # propósito: no es comparable con las sesiones de Claude, que se abren en
    # un segundo. Aquí caducar cuesta 13-42 s en el mensaje siguiente, y con
    # los 15 min de antes se pagaban a diario —se usa a ratos, no seguido—.
    antigravity_idle_seconds: int = 3600
    antigravity_max_sessions: int = 4
    # A qué ritmo se le teclea el turno por el pseudoterminal: caracteres por
    # bloque y pausa entre bloques. Calibrado contra la CLI real comprobando el
    # texto que registra: con 64 y 6 ms van 10.000 car/s y llega intacto cuatro
    # de cuatro veces en 1.500, 2.000 y 3.000 caracteres. Los valores de antes
    # (24 y 12 ms) daban 2.000 car/s, cinco veces más lento sin ganar nada.
    # Están en la configuración para poder retroceder sin recompilar; lo que se
    # pierde al ir rápido no lo ve un test, lo ve `HandleUserInput`.
    agy_type_chunk: int = 64
    agy_type_delay_ms: int = 6
    # Deja una sesión lista al arrancar el servidor para que el primer mensaje
    # no pague los ~10 s de apertura.
    antigravity_warm_up: bool = True

    # --- Navegador visible (MCP de Playwright) ---
    # El servidor de Playwright no corre aquí sino en tu ordenador, lanzado por
    # el agente de `agent/`: un navegador abierto dentro del contenedor no lo
    # vería nadie. `agy` se conecta a él por red y lo pilota desde ahí.
    playwright_mcp_enabled: bool = True
    playwright_mcp_port: int = 8931
    # Cómo ve el core la máquina donde está el navegador. Por defecto la suya:
    # el caso normal es el core corriendo en el ordenador del usuario, que es
    # lo que hace que `agy` viva ahí y sus herramientas nativas sean el disco
    # de verdad. En Docker hay que poner `host.docker.internal` —lo hace el
    # `docker-compose.yml` por entorno—, y si el nodo fuera otra máquina, aquí
    # va su nombre en la tailnet.
    playwright_mcp_host: str = "127.0.0.1"
    # Playwright sirve el mismo MCP en dos transportes. `/mcp` es el que
    # recomienda él mismo al arrancar (HTTP con streaming); `/sse` lo describe
    # como «legacy». `agy` lleva dentro un cliente de los primeros
    # (`streamableClientConn`), así que se le da el que espera.
    playwright_mcp_path: str = "/mcp"
    # En qué interfaz escucha el servidor, en la máquina donde se abre. Vacío =
    # solo localhost, que basta porque Docker Desktop hace de intermediario y
    # deja el puerto fuera del alcance de la red. Solo hay que tocarlo si el
    # nodo es una máquina distinta de la del contenedor, y entonces el puerto
    # queda expuesto: no pide credenciales.
    playwright_mcp_bind: str = ""
    # El navegador que abrirá: `chrome` usa el Chrome instalado, `chromium` el
    # que se descarga Playwright. Solo se usa en modo `perfil`.
    playwright_mcp_browser: str = "chrome"
    # Qué dispositivo abre el navegador. Vacío = el único que tengas conectado.
    playwright_mcp_device: str = ""
    # Quién es el dueño del navegador.
    #
    # `cdp`: el nodo abre un navegador suyo con el puerto de depuración puesto y
    # Playwright se engancha a él. El perfil es propio de Vibi y **persistente**:
    # lo que se inicie ahí sigue iniciado mañana, así que se entra una vez en
    # cada sitio y ya. Es lo que quieres casi siempre.
    #
    # Durante un tiempo esto se enganchaba al navegador de diario del usuario,
    # que era mejor —las sesiones ya estaban— pero solo funcionaba con Opera GX:
    # Chromium bloquea el puerto de depuración sobre el perfil por defecto desde
    # la 136. Y traía un fallo caro: con Opera abierto a mano, Vibi se quedaba
    # sin navegador y al modelo se le decía «no tienes Playwright».
    #
    # `perfil`: lo lanza Playwright, con un perfil de usar y tirar que no ha
    # iniciado sesión en nada. Era lo único que había al principio y se mantiene
    # como repliegue.
    playwright_mcp_mode: str = "cdp"
    # El puerto de depuración del navegador, en tu máquina. No tiene nada que
    # ver con `playwright_mcp_port`, que es el del servidor MCP.
    playwright_mcp_cdp_port: int = 9333
    # Qué navegador abre, por ruta y no por nombre.
    #
    # Va explícito y no se deduce del navegador por defecto del sistema porque
    # el navegador por defecto puede ser un Firefox —Zen lo es—, y Firefox no
    # habla CDP: deducirlo daría siempre el equivocado. Tiene que ser uno basado
    # en Chromium. Probado con Chrome 151, que sobre un `--user-data-dir` propio
    # abre el puerto en 0,5 s.
    playwright_mcp_browser_path: str = ""

    # --- El ordenador entero (MCP de sistema) ---
    # El disco y el intérprete de comandos de tu máquina, servidos por el
    # agente de `agent/`. Sin esto Vibi solo ve la carpeta del workspace,
    # que es lo único del ordenador que llega dentro del contenedor.
    system_mcp_enabled: bool = True
    system_mcp_port: int = 8932
    # Cómo ve el core la máquina cuyo disco se sirve. Mismo criterio que
    # `playwright_mcp_host`: por defecto la suya. En Docker lo pone el
    # `docker-compose.yml`; si el nodo fuera otro equipo, aquí va su nombre en
    # la tailnet, y entonces hay que abrir también SYSTEM_MCP_BIND.
    system_mcp_host: str = "127.0.0.1"
    # En qué interfaz escucha, en la máquina donde corre. Vacío = solo
    # localhost, que basta con el contenedor en ese mismo equipo y deja el
    # puerto fuera del alcance de la red. Al abrirlo, lo único que queda
    # delante del disco es el secreto que el agente pone en la ruta.
    system_mcp_bind: str = ""
    # Qué máquina. Vacío = la única que tengas conectada.
    system_mcp_device: str = ""

    # --- MCP de terceros para `agy` ---
    # Servidores que no son nuestros y que se declaran junto a los de Vibi.
    # La regla es la misma para todos: sin credencial no se declaran, y lo que
    # no se declara se borra de la configuración en vez de quedarse apuntando a
    # un sitio al que no se puede entrar.
    #
    # Los MCP oficiales de Google Workspace. `agy` sabe hacer su OAuth solo
    # —Google lo documenta como cliente soportado—, así que aquí solo van las
    # credenciales del cliente; el consentimiento se da una vez a mano y se
    # guarda en el volumen de `agy`, igual que el login.
    google_mcp_client_id: str = ""
    google_mcp_client_secret: str = ""
    # Cuáles de ellos quieres, separados por comas. Viene con los tres puestos,
    # pero sin cliente OAuth no se declara ninguno. Quitar un nombre de aquí es
    # la forma de apagar uno solo —Gmail, por ejemplo, que es por donde entra
    # más texto escrito por desconocidos— sin tocar las credenciales.
    google_mcp_servers: str = "calendar,gmail,drive"

    # --- Telegram ---
    telegram_bot_token: str = ""
    # chat_id autorizado en fase 1 (un solo usuario). 0 = aceptar el primero que haga /start
    telegram_owner_chat_id: int = 0

    # --- PWA / API ---
    jwt_secret: str = ""
    jwt_expiration_days: int = 30
    credential_encryption_key: str = ""
    pwa_base_url: str = "http://localhost:8000"
    frontend_dist: str = "./frontend/dist"
    git_clone_timeout_seconds: int = 300

    # --- Nodos ejecutores ---
    # Una orden dirigida a una máquina apagada espera hasta node_order_ttl y
    # después caduca: al encender un portátil olvidado no debe caerle encima
    # una tanda de órdenes viejas. El timeout corto es lo que aguanta una
    # conversación antes de contestar "aún está trabajando".
    node_order_ttl_seconds: int = 21_600  # 6 horas
    node_result_timeout_seconds: int = 45

    # --- Workspaces ---
    # Directorio raíz donde viven los proyectos sobre los que trabaja el agente.
    # En fase 2 esto será /home/<usuario>/workspace por cada user de Linux.
    workspace_root: str = "./workspace"

    # --- Forja de herramientas (guiones que Vibi se escribe a sí misma) ---
    # El guion lo redacta Claude, no el motor de chat: un guion que se guarda
    # y se repite tiene que salir bien la primera vez, y Gemini fallaba ahí.
    # Haiku 4.5 es suficiente para un archivo de cien líneas y es el barato.
    forja_modelo: str = "claude-haiku-4-5"
    # Cuánto puede tardar un guion en responder. Corto a propósito: esto se
    # ejecuta dentro de un turno de conversación, con alguien esperando.
    forja_timeout_seconds: int = 30
    # Techo de lo que un guion puede devolver e imprimir. Un bucle que escupe
    # megabytes no puede llenar ni la respuesta del modelo ni la memoria.
    forja_max_salida_bytes: int = 200_000
    # Memoria del proceso del guion (solo POSIX; en Windows no hay rlimit).
    forja_memoria_mb: int = 512

    # --- Archivos personales ---
    # Ubicación histórica de blobs pendientes de migrar. Las subidas nuevas
    # viven en WORKSPACE_ROOT/<user_id>/Archivos subidos para que los motores
    # de Vibi puedan abrirlas directamente por su nombre.
    file_storage_root: str = "./data/files"
    file_max_bytes: int = 100_000_000
    file_user_quota_bytes: int = 2_000_000_000
    file_scan_limit: int = 10_000
    file_search_limit: int = 100
    file_content_index_chars: int = 12_000
    file_content_read_chars: int = 40_000
    file_content_max_bytes: int = 25_000_000

    # --- Base de datos ---
    db_path: str = Field(
        default_factory=lambda: str(
            resolve_vibi_db_path(Path("./data/vibi.db"), Path("./data/morgana.db"))
        )
    )


settings = Settings()
