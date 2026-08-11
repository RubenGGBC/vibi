"""Procedencia del contexto: de dónde salió la idea de ejecutar algo.

La inyección de prompts no aparece de la nada. Entra por contenido que Vibi
**lee**: un README con instrucciones escondidas, un resultado de búsqueda web,
la salida de un comando en otra máquina. Tu voz diciendo «ponme música» no es
un vector; el archivo que acaba de leer, sí.

De ahí la idea: en vez de preguntarnos «¿este comando parece peligroso?»
—que es indecidible, porque bash es un lenguaje completo— nos preguntamos
«¿ha leído algo de fuera antes de querer ejecutar esto?», que sí se puede
responder con certeza. Si lo ha leído, la ejecución pasa por ti.

Límite conocido y aceptado: la marca vive en memoria y se ata al usuario, no
al turno concreto, porque las primitivas reciben `user`, no la conversación.
Al reiniciar el servidor se olvida. Los dos errores caen del lado seguro:
se pide confirmación de más, nunca de menos.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# Cuánto dura la sospecha. Un turno agéntico largo puede leer un archivo al
# principio y querer ejecutar algo cinco minutos después: la marca tiene que
# sobrevivir a eso. Pasado el rato, la conversación ya es otra cosa.
VENTANA_SEGUNDOS = 600.0

# Primitivas que meten en el contexto texto que no has escrito tú. Si añades
# una capacidad que devuelva contenido ajeno, su nombre va aquí.
#
# Lo que viene de una máquina se nombra `devices.<capacidad>`, tal como lo
# construye `nodes.entregar_y_esperar`. Las claves con guion bajo que había
# antes no casaban con nada y su frase no llegó a verse nunca.
FUENTES_EXTERNAS = {
    "files.read": "un archivo tuyo",
    "files.search": "una búsqueda en tus archivos",
    "devices.shell.run": "la salida de un comando en otra máquina",
    "devices.files.search": "una búsqueda de archivos en otra máquina",
    "devices.files.push": "un archivo traído de otra máquina",
    "devices.projects.list": "la lista de proyectos de otra máquina",
    "web.search": "una búsqueda web",
    # El título de un vídeo lo escribe quien lo subió. Es texto de un
    # desconocido entrando en el contexto, igual que una página web.
    "devices.media.now_playing": "el título de lo que estás escuchando",
    # Lo que tuvieras abierto al pedir la captura lo escribió cualquiera. Que
    # entre como imagen y no como texto no cambia de quién es: un modelo lee lo
    # que pone en una pantalla igual que lo que pone en un archivo.
    "devices.screen.capture": "lo que había en tu pantalla",
    "telegram.document": "un archivo que has mandado por Telegram",
    # Los MCP de terceros que usa `agy` (ver `executors/agy_mcp_config.py`).
    # Estos no pasan por `tools.execute`, así que no se marcan solos: los marca
    # `antigravity_chat` al ver el paso en el stream del turno. Son la mayor
    # entrada de texto ajeno que hay —un correo lo escribe cualquiera— y por
    # eso importa que estén.
    "agy.exa": "una búsqueda en la web",
    # El disco de tu ordenador, servido por el agente del nodo. Cuenta como
    # fuente externa aunque los archivos sean «tuyos»: un PDF que te bajaste o
    # el README de un repo clonado los escribió otro.
    "agy.pc": "un archivo de tu ordenador",
    # El navegador, desde que navega con tu perfil. Lo que pone en una web lo
    # escribió cualquiera, y ahora ese cualquiera le habla a una sesión tuya
    # iniciada: es la entrada de texto ajeno con más alcance que hay.
    "agy.playwright": "una página web",
    "agy.gmail": "un correo tuyo",
    "agy.drive": "un documento de tu Drive",
    "agy.calendar": "tu agenda",
    # Cuando el stream dice que se ejecutó una herramienta pero no cuál. Pasa
    # de largo hacia el lado seguro: con servidores externos declarados, no se
    # puede descartar que lo que acaba de entrar venga de fuera.
    "agy.mcp": "el resultado de una herramienta externa",
}


@dataclass(frozen=True)
class Marca:
    fuente: str
    descripcion: str
    momento: float


class RegistroProcedencia:
    """Qué contenido externo ha tocado cada usuario y hace cuánto."""

    def __init__(self, ventana_segundos: float = VENTANA_SEGUNDOS) -> None:
        self._ventana = ventana_segundos
        self._marcas: dict[str, list[Marca]] = {}
        self._lock = threading.Lock()

    def marcar(self, user_id: str, fuente: str, descripcion: str | None = None) -> None:
        descripcion = descripcion or FUENTES_EXTERNAS.get(fuente, fuente)
        with self._lock:
            marcas = [
                marca
                for marca in self._marcas.get(user_id, [])
                if marca.fuente != fuente
            ]
            marcas.append(Marca(fuente, descripcion, time.monotonic()))
            self._marcas[user_id] = marcas

    def marcas_vivas(self, user_id: str) -> list[Marca]:
        limite = time.monotonic() - self._ventana
        with self._lock:
            marcas = [
                marca for marca in self._marcas.get(user_id, []) if marca.momento > limite
            ]
            if marcas:
                self._marcas[user_id] = marcas
            else:
                self._marcas.pop(user_id, None)
            return marcas

    def contaminado(self, user_id: str) -> bool:
        return bool(self.marcas_vivas(user_id))

    def motivo(self, user_id: str) -> str | None:
        """Frase para explicarte en la UI por qué te estamos preguntando."""
        marcas = self.marcas_vivas(user_id)
        if not marcas:
            return None
        reciente = max(marcas, key=lambda marca: marca.momento)
        if len(marcas) == 1:
            return f"En este turno Vibi ha leído {reciente.descripcion}"
        return (
            f"En este turno Vibi ha leído contenido externo "
            f"({len(marcas)} fuentes, la última: {reciente.descripcion})"
        )

    def limpiar(self, user_id: str) -> None:
        """Al empezar de cero, la sospecha también se va."""
        with self._lock:
            self._marcas.pop(user_id, None)


registro = RegistroProcedencia()
