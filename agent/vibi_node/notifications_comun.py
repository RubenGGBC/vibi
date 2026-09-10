"""Lo que vale igual en cualquier ordenador que sepa contar sus notificaciones.

Esto vivía dentro de `notifications_windows` porque durante un tiempo Windows
fue el único que leía nada. No tiene una línea de Windows dentro: es la forma de
un aviso una vez limpio, y la memoria de cuáles ya se contaron. Al aparecer el
lector de macOS, dejarlo allí habría obligado a un módulo a importar el del otro
sistema para usar su `dataclass`, y a un Mac a cargar WinRT para nada.

De paso, sacarlo aquí hace que sus pruebas corran en cualquier máquina. Mientras
`Vigia` estuvo en el módulo de Windows, su prueba se saltaba sola en un Mac
—`skipUnless`— aunque no hubiera nada que saltarse.
"""
from __future__ import annotations

from dataclasses import dataclass

# Cuánto se espera entre sondeos. Corto porque «Ana te ha escrito» dicho medio
# minuto tarde ya no sirve de nada, y se puede permitir porque la espera no
# consume CPU: en los dos sistemas la lectura está parada, no trabajando.
INTERVALO = 1.5

# Cuántas notificaciones se recuerdan para no repetirse. Un equipo encendido
# semanas no puede ir acumulando identidades para siempre.
MAX_VISTAS = 2_000

APP_DESCONOCIDA = "desconocida"


class ErrorNotificaciones(Exception):
    pass


@dataclass(frozen=True)
class Aviso:
    """Una notificación, ya sin nada del sistema operativo dentro.

    `id` es de tipo ancho a propósito. En Windows es el entero que da
    `UserNotificationListener`, que crece y no se recicla. En macOS **no puede
    ser** el entero de la fila: al descartar una notificación se borra la fila y
    ese número vuelve a estar libre, así que allí la identidad es el UUID del
    registro. Lo único que se le pide es que sirva de clave y no se repita.

    El servidor no lo mira —`sanear()` en `app/avisos.py` se queda con `app`,
    `titulo` y `cuerpo` y tira el resto—, así que es asunto interno del nodo.
    """

    id: int | str
    app: str
    titulo: str
    cuerpo: str
    cuando: str

    def __str__(self) -> str:
        cabeza = f"[{self.app}] {self.titulo}".strip()
        return f"{cabeza}: {self.cuerpo}" if self.cuerpo else cabeza


class Vigia:
    """Recuerda qué notificaciones ya se contaron.

    Hace falta porque en los dos sistemas cada sondeo devuelve el centro entero
    y no lo nuevo: sin memoria, Vibi te leería los mismos ocho avisos cada
    segundo y medio.

    El primer sondeo no devuelve nada a propósito: lo que hay en el centro al
    encender el agente lleva ahí desde antes y ya lo has visto.
    """

    def __init__(self) -> None:
        self._vistas: dict[int | str, None] = {}
        self._estrenado = False

    def novedades(self, avisos: list[Aviso]) -> list[Aviso]:
        nuevas = [a for a in avisos if a.id not in self._vistas]
        for aviso in avisos:
            # Reinsertar mueve la clave al final: así podar tira lo antiguo y
            # no lo que sigue en pantalla.
            self._vistas.pop(aviso.id, None)
            self._vistas[aviso.id] = None
        self._podar()
        if not self._estrenado:
            self._estrenado = True
            return []
        return nuevas

    def _podar(self) -> None:
        sobran = len(self._vistas) - MAX_VISTAS
        for _ in range(max(0, sobran)):
            self._vistas.pop(next(iter(self._vistas)))
