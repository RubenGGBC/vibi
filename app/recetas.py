"""Lo que Vibi ha aprendido sobre cómo se maneja cada aplicación.

**Una receta es una instrucción, no un recuerdo.** «El martes le escribí a
Ruffini» no sirve para nada; «los chats están en `#pane-side` y el cuadro de
texto es `div[contenteditable][data-tab=10]`» sirve siempre. Lo que se guarda
aquí es lo segundo, con huecos donde iba lo de aquella vez.

**Por qué existe esto**, medido el 21 de agosto de 2026 contra WhatsApp: la
primera vez que Vibi lo manejó por CDP tardó **155 s y 47 llamadas**, de las
cuales 40 fueron tanteo del DOM —probando selectores a ver cuál existía—. De
todo aquello solo cuatro cosas resultaron ser ciertas. Guardarlas convierte la
siguiente vez en dos llamadas. El cuello de botella nunca fue lo que tarda el
ordenador —el árbol son 251 ms y el DOM 31 ms—, sino **cuántas veces hay que
preguntarle al modelo**, que son 2,7 s cada una.

**Y la regla que sostiene todo lo demás: solo se guarda lo verificado.** Hay un
estudio dedicado a cómo falla esta clase de memoria en agentes de interfaz
(«Naive Visual Memory is Not Enough», arXiv 2606.14106) y su hallazgo es que
con recetas obsoletas la tasa de éxito cae **por debajo de no tener memoria**:
el agente confía en lo guardado sin validarlo y falla sin enterarse. Es decir,
mal hecho esto no mejora el sistema, lo empeora — y encima convierte en
permanente el defecto de dar por hecha una tarea que no se comprobó. De ahí
`RecetaNoVerificada` y de ahí que la receta sepa retirarse sola.

La forma de guardar y recuperar viene de dos trabajos que llegaron a lo mismo:
la librería de habilidades con autoverificación de Voyager (arXiv 2305.16291)
y la provisión selectiva de Agent Workflow Memory (arXiv 2409.07429), que
reporta reducir el número de pasos además de acertar más.
"""
from __future__ import annotations

import time
import unicodedata

from . import db

# Por dónde se maneja la aplicación. No es cosmético: el DOM y el árbol de
# accesibilidad nombran las cosas de forma distinta, así que una receta escrita
# para uno no vale para el otro.
VIAS = frozenset({"cdp", "arbol"})

# Fallos seguidos que aguanta una receta antes de retirarse. Uno suelto puede
# ser la ventana a medio cargar o la red; tres seguidos es que la aplicación
# cambió por dentro y lo guardado ya no describe lo que hay.
FALLOS_PARA_RETIRAR = 3

# Tope de lo que ocupa una receta. Subido de 4.000 a 12.000 el 22/08/2026, al
# pasar de guardar trazas a guardar **mapas**: describir qué es cada parte de la
# interfaz —y darle sus dos direcciones, la del DOM y la del árbol— ocupa varias
# veces lo que ocupaba apuntar los cuatro selectores de un camino concreto. Sigue
# acotado, y por el mismo motivo de siempre: esto entra en el contexto del modelo
# cada vez que toca esa aplicación. Un mapa que no cabe aquí es un mapa que está
# describiendo cosas que nadie usó.
MAX_CONTENIDO = 12_000


class RecetaError(Exception):
    """Algo que impide guardar o usar una receta."""


class RecetaInvalida(RecetaError):
    pass


class RecetaNoVerificada(RecetaError):
    """Se intentó guardar un camino que nadie comprobó que funcione."""


def crear_tablas() -> None:
    with db._conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS recetas (
            app            TEXT PRIMARY KEY,
            via            TEXT NOT NULL CHECK (via IN ('cdp', 'arbol')),
            contenido      TEXT NOT NULL,
            comprobacion   TEXT NOT NULL DEFAULT '',
            fallos         INTEGER NOT NULL DEFAULT 0,
            verificada_en  REAL NOT NULL,
            creada_en      REAL NOT NULL
        );
        """)


def normalizar(nombre: object) -> str:
    """El nombre de una aplicación, como clave.

    Sin tildes ni mayúsculas ni espacios de sobra, que quien pregunta la nombra
    como le sale: «WhatsApp», «whatsapp», «el WhatsApp».
    """
    plano = unicodedata.normalize("NFKD", str(nombre or ""))
    plano = plano.encode("ascii", "ignore").decode("ascii").casefold()
    return " ".join(plano.split())


def guardar(
    app: str,
    via: str,
    contenido: object,
    verificada: bool = True,
    comprobacion: object = "",
) -> dict:
    """Apunta lo aprendido sobre una aplicación, si es que se comprobó.

    `verificada` no tiene valor por defecto `False` a propósito: quien llame
    tiene que haber comprobado que el camino funciona, y pasar `False` es
    decir «no lo comprobé», que aquí es un error y no una advertencia.

    `comprobacion` es el texto de **qué** se comprobó. No se valida aquí —lo
    exige la herramienta, que es quien habla con el modelo— pero se guarda,
    porque el día que una receta salga mala lo primero que hay que poder mirar
    es con qué prueba se dio por buena.
    """
    clave = normalizar(app)
    if not clave:
        raise RecetaInvalida("Una receta necesita saber de qué aplicación es")
    if via not in VIAS:
        raise RecetaInvalida(
            f"«{via}» no es una vía conocida; son {', '.join(sorted(VIAS))}"
        )
    texto = str(contenido or "").strip()
    if not texto:
        raise RecetaInvalida("Una receta vacía no dice cómo hacer nada")
    if len(texto) > MAX_CONTENIDO:
        raise RecetaInvalida(
            f"La receta pasa de {MAX_CONTENIDO} caracteres: resume lo que vale "
            "y tira el tanteo"
        )
    if not verificada:
        raise RecetaNoVerificada(
            "Solo se guarda lo que se comprobó que funciona: una receta sin "
            "verificar se repite convencida y falla sin avisar"
        )

    ahora = time.time()
    with db._conn() as c:
        c.execute(
            """
            INSERT INTO recetas (app, via, contenido, comprobacion, fallos,
                                 verificada_en, creada_en)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(app) DO UPDATE SET
                via = excluded.via,
                contenido = excluded.contenido,
                comprobacion = excluded.comprobacion,
                fallos = 0,
                verificada_en = excluded.verificada_en
            """,
            (clave, via, texto, str(comprobacion or "").strip(), ahora, ahora),
        )
    return receta_de(clave)


def _fila_de(c, clave: str):
    """La receta de esa aplicación, buscándola como la nombraría una persona.

    Primero exacta y luego por trozos: la aplicación se apunta como la conoce
    el sistema —`whatsappdesktop`— y se pide como la llama quien habla.
    """
    fila = c.execute("SELECT * FROM recetas WHERE app = ?", (clave,)).fetchone()
    if fila:
        return fila
    for otra in c.execute("SELECT * FROM recetas"):
        guardada = otra["app"]
        if clave in guardada or guardada in clave:
            return otra
    return None


def receta_de(app: str) -> dict | None:
    """Lo que se sabe de esa aplicación, o nada si no se sabe todavía."""
    clave = normalizar(app)
    if not clave:
        return None
    with db._conn() as c:
        fila = _fila_de(c, clave)
    return dict(fila) if fila else None


def registrar_fallo(app: str) -> None:
    """Esta receta no ha funcionado esta vez.

    A los `FALLOS_PARA_RETIRAR` seguidos se borra, y la próxima vez se vuelve a
    aprender desde cero. Retirarla es más barato que arrastrarla: una receta
    muerta hace fallar la tarea *y* además hace creer que salió bien.
    """
    clave = normalizar(app)
    if not clave:
        return
    with db._conn() as c:
        fila = _fila_de(c, clave)
        if not fila:
            return
        fallos = fila["fallos"] + 1
        if fallos >= FALLOS_PARA_RETIRAR:
            c.execute("DELETE FROM recetas WHERE app = ?", (fila["app"],))
        else:
            c.execute(
                "UPDATE recetas SET fallos = ? WHERE app = ?",
                (fallos, fila["app"]),
            )


def marcar_acierto(app: str) -> None:
    """Ha vuelto a funcionar: se le perdonan los fallos sueltos."""
    clave = normalizar(app)
    if not clave:
        return
    with db._conn() as c:
        fila = _fila_de(c, clave)
        if not fila:
            return
        c.execute(
            "UPDATE recetas SET fallos = 0, verificada_en = ? WHERE app = ?",
            (time.time(), fila["app"]),
        )


def todas() -> list[dict]:
    """Todo lo que Vibi sabe manejar, para poder contarlo."""
    with db._conn() as c:
        return [dict(f) for f in c.execute("SELECT * FROM recetas ORDER BY app")]


def olvidar(app: str) -> None:
    clave = normalizar(app)
    with db._conn() as c:
        fila = _fila_de(c, clave)
        if fila:
            c.execute("DELETE FROM recetas WHERE app = ?", (fila["app"],))
