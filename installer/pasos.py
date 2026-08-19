"""La instalación en sí, contada paso a paso mientras ocurre.

Cada paso avisa antes de empezar y al terminar, porque el que más tarda —pip—
puede pasarse dos minutos sin decir nada y una pantalla quieta parece colgada.
Lo que se emite aquí es lo que se lee en el asistente, así que va escrito para
leerse, no para depurar.

**Solo biblioteca estándar.**
"""
from __future__ import annotations

from pathlib import Path

from . import acciones, deteccion

# Lo que se le concede al core para abrir el puerto. Generoso porque el primer
# arranque construye la base de datos y carga el bot de Telegram; medido en esta
# máquina, unos 6 s. Pasado esto es que algo va mal y hay que decirlo, no seguir
# esperando con una pantalla quieta.
ESPERA_ARRANQUE = 45.0

# Lo que se ofrece elegir, con lo que de verdad cambia entre ellos. Medido en
# esta máquina: entre `flash-medium` y `flash-low` no hay diferencia apreciable
# de tiempo (1,16 s frente a 1,17 s en charla), así que la elección va por
# cabeza y no por velocidad — y por eso el texto no promete rapidez.
MODELOS = [
    {
        "clave": "gemini-3.6-flash-medium",
        "nombre": "Flash",
        "descripcion": "Rápida y suficiente para casi todo. La recomendada.",
        "recomendado": True,
    },
    {
        "clave": "gemini-3.6-flash-high",
        "nombre": "Flash, pensando más",
        "descripcion": "Razona mejor en lo enrevesado. Tarda algo más.",
        "recomendado": False,
    },
    {
        "clave": "gemini-3.1-pro-high",
        "nombre": "Pro",
        "descripcion": "La más capaz, para trabajo largo. Gasta más cuota.",
        "recomendado": False,
    },
]


def instalar(eleccion: dict, avisar, instalador_agy=None) -> None:
    """Deja Vibi instalada y lista, avisando de cada paso.

    El orden no es libre. `agy` va primero porque es el motor y sin él lo demás
    no sirve de nada; el entorno antes que el resto porque todo corre con su
    intérprete; la cuenta después de las dependencias porque crearla necesita
    `app.db`, que aún no existiría; y el arranque el último, para no dejar en
    marcha algo a medio configurar.
    """
    raiz = deteccion.raiz_del_repo()
    so = deteccion.sistema_operativo()

    if instalador_agy is not None and not instalador_agy.donde_esta():
        avisar("paso", clave="agy", texto="Instalando Antigravity, que es su motor")
        proceso = instalador_agy.instalar(so)
        for linea in proceso.stdout or ():
            limpia = linea.rstrip()
            if limpia:
                avisar("detalle", clave="agy", texto=limpia)
        if proceso.wait() != 0:
            raise RuntimeError(
                "No se ha podido instalar Antigravity. Lo de arriba dice por qué."
            )
        ruta = instalador_agy.donde_esta()
        if not ruta:
            raise RuntimeError(
                "Antigravity dice que se instaló, pero no aparece por ninguna parte."
            )
        avisar("hecho", clave="agy", detalle=ruta)

    avisar("paso", clave="entorno", texto="Preparando un rincón propio para Vibi")
    python = acciones.crear_entorno(raiz)
    avisar("hecho", clave="entorno", detalle=str(python))

    avisar(
        "paso",
        clave="dependencias",
        texto="Trayendo lo que necesita para funcionar",
    )
    proceso = acciones.instalar_dependencias(raiz, python)
    for linea in proceso.stdout or ():
        limpia = linea.rstrip()
        if limpia:
            avisar("detalle", clave="dependencias", texto=limpia)
    if proceso.wait() != 0:
        raise RuntimeError(
            "No se pudieron instalar las dependencias. Lo de arriba dice por qué."
        )
    avisar("hecho", clave="dependencias")

    avisar("paso", clave="ajustes", texto="Guardando lo que has elegido")
    acciones.escribir_env(raiz, eleccion)
    avisar("hecho", clave="ajustes")

    nombre = (eleccion.get("usuario") or "").strip()
    password = eleccion.get("password") or ""
    if nombre and password:
        avisar("paso", clave="cuenta", texto=f"Creando tu cuenta, {nombre}")
        acciones.crear_usuario(
            raiz,
            python,
            nombre,
            password,
            motor=eleccion.get("motor") or "antigravity",
            modelo=eleccion.get("modelo") or "",
        )
        avisar("hecho", clave="cuenta")

    avisar("paso", clave="arranque", texto="Despertándola")
    guion = acciones.escribir_arranque(so, raiz)

    # Arrancarla es parte de instalar. La primera versión acababa enseñando la
    # ruta de un `.cmd` y dejaba al usuario mirando un «Vibi está despierta»
    # con absolutamente nada corriendo.
    url = "http://127.0.0.1:8000"
    if acciones.esperar_a_vibi(url, 2):
        # Ya estaba en pie —una reinstalación, o el guion de arranque del
        # sistema—: levantar otra costaría el puerto y dos procesos peleándose.
        avisar("detalle", clave="arranque", texto="Ya estaba en marcha.")
        viva = True
    else:
        acciones.arrancar_vibi(so, raiz)
        avisar("detalle", clave="arranque", texto="Esperando a que conteste…")
        viva = acciones.esperar_a_vibi(url, ESPERA_ARRANQUE)

    if not viva:
        raise RuntimeError(
            "Vibi se ha instalado, pero no ha llegado a arrancar. Prueba a "
            f"lanzarla a mano con:  {guion}"
        )
    avisar("hecho", clave="arranque", detalle=guion)

    avisar("resumen", guion=guion, url=url, carpeta=str(Path(raiz)))
