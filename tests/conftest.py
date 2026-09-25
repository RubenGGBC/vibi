"""Que la suite no escriba en la base de verdad.

Hasta el 24/08/2026 sí lo hacía, y no era inofensivo: los cuatro tests de
`CaidaAClaude` pasan por `chat._run_with_fallback`, que registra un evento
`motor_caido` de verdad. Parcheaban el motor, el historial y el precalentado,
pero no `db.log_event`, así que cada `pytest` dejaba cuatro caídas falsas en
`data/vibi.db`.

Llegaron a ser **600 de las 683** que había: el histórico decía que el motivo
número uno de caída con diferencia era «agy no responde», que es un texto que
solo existe en los tests. Mirando ahí, cualquier diagnóstico empieza por la
pista falsa —y las 83 reales, que son las que importan, quedaban enterradas.

`db._conn()` lee `settings.db_path` en cada llamada, así que redirigirlo aquí
basta para toda la suite, sin tocar un solo test.
"""
import os
import tempfile
from pathlib import Path

from app import db
from app.config import settings

BASE_DE_PRUEBAS = Path(tempfile.gettempdir()) / "vibi-tests" / f"vibi-{os.getpid()}.db"


def pytest_configure(config) -> None:
    """Antes de recolectar nada: la base pasa a ser una de usar y tirar."""
    BASE_DE_PRUEBAS.parent.mkdir(parents=True, exist_ok=True)
    # Cada ejecución empieza limpia. Si un test se apoyara en lo que dejó otro,
    # es mejor que se vea aquí y no contra los datos del usuario.
    BASE_DE_PRUEBAS.unlink(missing_ok=True)
    settings.db_path = str(BASE_DE_PRUEBAS)
    db.init_db()


def pytest_sessionstart(session) -> None:
    """Y que no le pregunte nada a Jev de verdad.

    La clave de Opper vive en el `.env`, que lo leen tanto el servidor
    (`settings`) como el nodo (`decisor._clave_del_env`). Con ella puesta, los
    tests del triaje de avisos y de `fast_actions` salían a la red y
    contestaba el modelo de verdad en vez del camino que probaban. Quien
    necesite la clave la pone él, como ya hacen `test_decisor*`.
    """
    settings.opper_api_key = ""
    os.environ.pop("OPPER_API_KEY", None)
    # Lo mismo con Mercury: con MERCURY_PRINCIPAL en el `.env`, el router, los
    # avisos y el chat de la suite hablarían con Inception de verdad.
    settings.mercury_principal = False
    settings.mercury_api_key = ""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
    from vibi_node import decisor as decisor_del_nodo

    decisor_del_nodo._ENV_DEL_REPO = Path("/nonexistent/.env")
