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
import tempfile
from pathlib import Path

from app import db
from app.config import settings

BASE_DE_PRUEBAS = Path(tempfile.gettempdir()) / "vibi-tests" / "vibi.db"


def pytest_configure(config) -> None:
    """Antes de recolectar nada: la base pasa a ser una de usar y tirar."""
    BASE_DE_PRUEBAS.parent.mkdir(parents=True, exist_ok=True)
    # Cada ejecución empieza limpia. Si un test se apoyara en lo que dejó otro,
    # es mejor que se vea aquí y no contra los datos del usuario.
    BASE_DE_PRUEBAS.unlink(missing_ok=True)
    settings.db_path = str(BASE_DE_PRUEBAS)
    db.init_db()
