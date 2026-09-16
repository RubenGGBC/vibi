"""Herramientas que Vibi se escribe a sí misma: guiones de Python guardados.

El catálogo de `tools.py` es cerrado a propósito: una herramienta personal es
una composición sobre una primitiva revisada, y no puede cargar código. Eso
sigue igual. Lo que hay aquí es otra cosa y vive aparte por eso mismo.

Hay un hueco que ese catálogo no cubre: lo repetitivo y pequeño. Pasar una
columna de un CSV a otro formato, calcular las cuotas de un préstamo, sacar los
enlaces de un texto. Nada de eso merece una primitiva —ni una revisión, ni un
despliegue— y en cambio se pide muchas veces, un poco distinto cada vez. Hasta
ahora el modelo lo rehacía de cero en cada conversación, con el resultado
puesto en el chat y perdido al turno siguiente.

Una herramienta de guion es esa solución escrita una vez, probada antes de
guardarse y disponible después con parámetros. Quien la escribe es Claude
(`executors/claude_forja.py`), no el motor de chat que esté atendiendo.

**Lo que se ejecuta aquí es código generado, y eso es lo caro de esta idea.**
La contención es de proceso, no de sintaxis: un guion corre en un intérprete
aparte, aislado (`-I`), en un directorio temporal vacío, con un entorno
recortado a mano —sin las variables de Vibi, así que sin claves de API, sin
ruta de la base de datos y sin secreto de JWT—, con tope de tiempo, de memoria
y de salida. No se filtran los `import`: una lista negra de módulos da una
sensación de seguridad que no se sostiene, y la frontera de verdad es que ese
proceso no tenga a mano nada que valga la pena robar.

Lo que sí conserva es el disco del contenedor con los permisos del servidor.
Un guion escrito para hacer daño podría tocar el workspace del usuario. Se
acepta porque el guion lo redacta Claude a partir de una petición del propio
usuario, se le enseña entero antes de nada y queda guardado y consultable —no
es código que entre de fuera—, pero conviene tenerlo escrito.
"""
from __future__ import annotations

import asyncio
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    create_model,
)

from . import db
from .config import settings

PREFIJO = "script."
MAX_CODIGO = 20_000
MAX_PETICION = 2_000
MAX_PARAMETROS = 6
# Tres tiradas y no más. Cada una cuesta una llamada al modelo y la persona que
# lo pidió está esperando; si a la tercera el guion sigue sin arrancar, el
# problema no es la mala suerte y decirlo vale más que seguir intentándolo.
INTENTOS = 3

# Los tipos que puede tener un parámetro. Deliberadamente pocos: lo que entra
# lo rellena un modelo escribiendo JSON, y cada tipo compuesto es una forma más
# de equivocarse. Una lista se pasa como texto separado por comas.
TIPOS: dict[str, type] = {
    "texto": str,
    "entero": int,
    "decimal": float,
    "booleano": bool,
}

IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")

# El arranque que Vibi le pone al guion. Va aquí y no lo escribe el modelo:
# leer los argumentos y devolver el resultado es el contrato, y un contrato que
# se reescribe en cada generación no es un contrato.
ARNES = '''

# --- arranque añadido por Vibi ---
def _vibi_arranque() -> None:
    import json as _json
    import sys as _sys

    with open(_sys.argv[1], encoding="utf-8") as _entrada:
        _argumentos = _json.load(_entrada)
    _resultado = ejecutar(**_argumentos)
    if not isinstance(_resultado, dict):
        _resultado = {"resultado": _resultado}
    with open(_sys.argv[2], "w", encoding="utf-8") as _salida:
        _json.dump(_resultado, _salida, ensure_ascii=False, default=str)


if __name__ == "__main__":
    _vibi_arranque()
'''


class ForjaError(Exception):
    pass


class ManifiestoInvalido(ForjaError):
    """Lo que devolvió el modelo no es una herramienta que se pueda guardar."""


class ForjaFallida(ForjaError):
    """Se agotaron los intentos sin conseguir un guion utilizable."""


class GuionFallido(ForjaError):
    """El guion existía y se ejecutó, pero terminó mal."""


# ---------- manifiesto ----------

def _slug(valor: object) -> str:
    normalizado = unicodedata.normalize("NFKD", str(valor or ""))
    ascii_valor = normalizado.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_valor).strip("-")
    if not 3 <= len(slug) <= 48:
        raise ManifiestoInvalido(
            "`slug` debe tener entre 3 y 48 caracteres en minúsculas y guiones"
        )
    return slug


def _texto(valor: object, campo: str, minimo: int, maximo: int) -> str:
    limpio = str(valor or "").strip()
    if not minimo <= len(limpio) <= maximo:
        raise ManifiestoInvalido(
            f"`{campo}` debe tener entre {minimo} y {maximo} caracteres"
        )
    return limpio


def objeto_json(crudo: str) -> dict:
    """Saca el objeto JSON de la respuesta, aunque venga con adornos."""
    limpio = (crudo or "").strip()
    if limpio.startswith("```"):
        limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpio)
    try:
        return _dict(json.loads(limpio))
    except json.JSONDecodeError:
        pass
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio < 0 or fin <= inicio:
        raise ManifiestoInvalido("No devolviste un objeto JSON")
    try:
        return _dict(json.loads(limpio[inicio : fin + 1]))
    except json.JSONDecodeError as error:
        raise ManifiestoInvalido(f"El JSON no se puede leer: {error}") from error


def _dict(valor: object) -> dict:
    if not isinstance(valor, dict):
        raise ManifiestoInvalido("La respuesta tiene que ser un objeto JSON")
    return valor


def _parametros_declarados(valor: object) -> list[dict]:
    if valor in (None, ""):
        return []
    if not isinstance(valor, list):
        raise ManifiestoInvalido("`parametros` tiene que ser una lista")
    if len(valor) > MAX_PARAMETROS:
        raise ManifiestoInvalido(
            f"Una herramienta admite como mucho {MAX_PARAMETROS} parámetros"
        )
    parametros: list[dict] = []
    vistos: set[str] = set()
    for bruto in valor:
        if not isinstance(bruto, dict):
            raise ManifiestoInvalido("Cada parámetro es un objeto JSON")
        nombre = str(bruto.get("nombre") or "").strip()
        if not IDENTIFICADOR.match(nombre):
            raise ManifiestoInvalido(
                f"«{nombre}» no vale como nombre de parámetro: minúsculas, "
                "dígitos y guiones bajos, empezando por letra"
            )
        if nombre in vistos:
            raise ManifiestoInvalido(f"El parámetro «{nombre}» está repetido")
        vistos.add(nombre)
        tipo = str(bruto.get("tipo") or "").strip().lower()
        if tipo not in TIPOS:
            raise ManifiestoInvalido(
                f"El tipo de «{nombre}» debe ser uno de {', '.join(TIPOS)}"
            )
        parametro = {
            "nombre": nombre,
            "tipo": tipo,
            "descripcion": str(bruto.get("descripcion") or "").strip()[:300],
            "obligatorio": bool(bruto.get("obligatorio", True)),
        }
        if not parametro["obligatorio"]:
            parametro["por_defecto"] = _por_defecto(
                bruto.get("por_defecto"), tipo, nombre
            )
        parametros.append(parametro)
    return parametros


def _por_defecto(valor: object, tipo: str, nombre: str) -> object:
    """El valor por defecto, convertido al tipo que se declaró.

    Se comprueba aquí porque Pydantic no lo hace: un `default=` no se valida al
    construir el modelo, así que un `"muchas"` en un parámetro `entero` se
    guardaba tal cual y llegaba como texto a la primera llamada que omitiera el
    argumento —días después, en la ejecución de verdad, y no en la prueba, que
    va con argumentos explícitos—.
    """
    if valor is None:
        return None
    try:
        return TypeAdapter(TIPOS[tipo]).validate_python(valor)
    except ValidationError as error:
        raise ManifiestoInvalido(
            f"El valor por defecto de «{nombre}» no es un {tipo}: {valor!r}"
        ) from error


def _firma_del_guion(codigo: str) -> tuple[set[str], bool]:
    """Los nombres que acepta `ejecutar`, y si además recoge `**kwargs`."""
    try:
        arbol = ast.parse(codigo)
    except SyntaxError as error:
        raise ManifiestoInvalido(
            f"El código no compila: línea {error.lineno}, {error.msg}"
        ) from error
    for nodo in arbol.body:
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if nodo.name != "ejecutar":
            continue
        if isinstance(nodo, ast.AsyncFunctionDef):
            raise ManifiestoInvalido("`ejecutar` no puede ser `async def`")
        argumentos = nodo.args
        if argumentos.posonlyargs:
            # `ARNES` llama `ejecutar(**argumentos)`, así que un parámetro
            # solo-posicional pasa esta validación y luego revienta en cada
            # ejecución. Se caza aquí porque si el modelo no propone `prueba`
            # nadie más lo intenta antes de guardarla.
            raise ManifiestoInvalido(
                "`ejecutar` no puede tener parámetros solo-posicionales: "
                "quita la barra (`/`) de la firma, Vibi la llama por nombre"
            )
        nombres = {
            argumento.arg
            for argumento in (*argumentos.args, *argumentos.kwonlyargs)
        }
        return nombres, argumentos.kwarg is not None
    raise ManifiestoInvalido(
        "El código tiene que definir una función `ejecutar` en el nivel superior"
    )


def validar_manifiesto(bruto: dict) -> dict:
    """Convierte lo que devolvió el modelo en algo guardable, o lo rechaza."""
    if bruto.get("error"):
        raise ForjaFallida(str(bruto["error"])[:500])

    codigo = str(bruto.get("codigo") or "").strip()
    if not codigo:
        raise ManifiestoInvalido("Falta `codigo`")
    if len(codigo) > MAX_CODIGO:
        raise ManifiestoInvalido(
            f"El guion pasa de {MAX_CODIGO} caracteres: hazlo más pequeño"
        )
    parametros = _parametros_declarados(bruto.get("parametros"))
    declarados = {parametro["nombre"] for parametro in parametros}
    firma, admite_kwargs = _firma_del_guion(codigo)
    if not admite_kwargs and firma != declarados:
        raise ManifiestoInvalido(
            f"`ejecutar{tuple(sorted(firma))}` no encaja con los parámetros "
            f"declarados {tuple(sorted(declarados))}: tienen que ser los mismos"
        )
    if admite_kwargs and not declarados >= (firma - {"kwargs"}):
        raise ManifiestoInvalido(
            "`ejecutar` pide nombres que no has declarado en `parametros`"
        )

    prueba = bruto.get("prueba")
    manifiesto = {
        "slug": _slug(bruto.get("slug") or bruto.get("nombre")),
        "name": _texto(bruto.get("nombre") or bruto.get("name"), "nombre", 3, 80),
        "description": _texto(
            bruto.get("descripcion") or bruto.get("description"),
            "descripcion", 30, 500,
        ),
        "parametros": parametros,
        "codigo": codigo,
        "prueba": prueba if isinstance(prueba, dict) else None,
        "notas": str(bruto.get("notas") or "").strip()[:500],
    }
    # Los valores por defecto ya los comprobó `_por_defecto` uno a uno; esto
    # es lo que queda: que el conjunto se pueda montar como modelo Pydantic.
    modelo_de(manifiesto["parametros"])
    return manifiesto


# ---------- argumentos ----------

@lru_cache(maxsize=256)
def _modelo_cacheado(firma: str) -> type[BaseModel]:
    campos: dict[str, tuple] = {}
    for parametro in json.loads(firma):
        tipo = TIPOS[parametro["tipo"]]
        descripcion = parametro["descripcion"] or None
        if parametro["obligatorio"]:
            anotacion: object = tipo
            campo = Field(description=descripcion)
        elif parametro.get("por_defecto") is None:
            anotacion = tipo | None
            campo = Field(default=None, description=descripcion)
        else:
            anotacion = tipo
            campo = Field(default=parametro["por_defecto"], description=descripcion)
        # `create_model` quiere (anotación, Field): el Field lleva dentro si
        # es obligatorio o qué valor toma cuando no lo mandan.
        campos[parametro["nombre"]] = (anotacion, campo)
    modelo = create_model(
        "ArgumentosDeGuion",
        # `validate_default` es la red de seguridad de `_por_defecto`: sin él
        # Pydantic entrega el default tal cual esté guardado, y una fila vieja
        # con un valor de otro tipo se colaría hasta dentro del guion.
        __config__=ConfigDict(extra="forbid", validate_default=True),
        **campos,
    )
    return modelo


def modelo_de(parametros: list[dict]) -> type[BaseModel]:
    """El modelo Pydantic que valida los argumentos de un guion."""
    try:
        firma = json.dumps(parametros, sort_keys=True, ensure_ascii=False)
        return _modelo_cacheado(firma)
    except ValidationError as error:
        raise ManifiestoInvalido(
            f"Un valor por defecto no es válido: {error}"
        ) from error
    except (TypeError, ValueError) as error:
        raise ManifiestoInvalido(f"Los parámetros no son válidos: {error}") from error


def esquema_de(parametros: list[dict]) -> dict:
    esquema = modelo_de(parametros).model_json_schema()
    esquema["additionalProperties"] = False
    return esquema


# ---------- ejecución ----------

def _entorno(carpeta: str) -> dict[str, str]:
    """Lo mínimo para que Python arranque, y nada de Vibi.

    Es la frontera importante: el proceso del guion no ve `ANTHROPIC_API_KEY`,
    ni `GROQ_API_KEY`, ni `JWT_SECRET`, ni la ruta de la base de datos. Se
    construye por lista blanca porque un `os.environ.copy()` al que se le
    quitan cuatro claves vuelve a filtrar la quinta que se añada mañana.
    """
    entorno = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": carpeta,
        "TMPDIR": carpeta,
        "TEMP": carpeta,
        "TMP": carpeta,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }
    # Sin estas, un Python de Windows no llega ni a arrancar.
    for llave in ("SystemRoot", "COMSPEC", "PATHEXT", "WINDIR", "NUMBER_OF_PROCESSORS"):
        if llave in os.environ:
            entorno[llave] = os.environ[llave]
    return entorno


def _limites() -> dict:
    """Techo de memoria y de CPU del guion, donde el sistema lo permita."""
    if os.name != "posix":
        return {}
    import resource  # noqa: PLC0415 - solo existe en POSIX

    memoria = max(64, settings.forja_memoria_mb) * 1024 * 1024
    cpu = max(1, settings.forja_timeout_seconds)

    def _aplicar() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (memoria, memoria))
        # El tope de CPU es la red de seguridad del tope de reloj: un bucle
        # cerrado no siempre muere al matarle el proceso padre la espera.
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))

    return {"preexec_fn": _aplicar}


async def _leer_recortado(stream, tope: int) -> str:
    """Vacía la tubería sin quedarse con más de `tope` bytes.

    Hay que vaciarla entera —si no, un guion parlanchín se bloquea al llenarla
    y muere por tiempo en vez de por lo que de verdad le pasa—, pero guardar
    todo lo que escupa un bucle infinito es un problema de memoria del
    servidor, no del guion.
    """
    trozos: list[bytes] = []
    total = 0
    while True:
        trozo = await stream.read(64 * 1024)
        if not trozo:
            break
        if total < tope:
            trozos.append(trozo[: tope - total])
        total += len(trozo)
    texto = b"".join(trozos).decode("utf-8", "replace")
    if total > tope:
        return f"{texto}\n[salida recortada]"
    return texto


async def ejecutar_guion(guion: dict, argumentos: dict) -> dict:
    """Corre el guion en un proceso aparte y devuelve lo que produjo."""
    codigo = guion["codigo"]
    timeout = max(1, settings.forja_timeout_seconds)
    tope = max(1_000, settings.forja_max_salida_bytes)

    with tempfile.TemporaryDirectory(prefix="vibi-forja-") as carpeta:
        base = Path(carpeta)
        archivo = base / "herramienta.py"
        entrada = base / "argumentos.json"
        salida = base / "resultado.json"
        archivo.write_text(codigo + ARNES, encoding="utf-8")
        entrada.write_text(
            json.dumps(argumentos, ensure_ascii=False, default=str), encoding="utf-8"
        )

        proceso = await asyncio.create_subprocess_exec(
            # -I aísla el intérprete: ni variables PYTHON*, ni `site` del
            # usuario, ni el directorio del guion en el `sys.path`.
            sys.executable, "-I", "-B", str(archivo), str(entrada), str(salida),
            cwd=carpeta,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_entorno(carpeta),
            **_limites(),
        )
        try:
            impreso, error, codigo_salida = await asyncio.wait_for(
                asyncio.gather(
                    _leer_recortado(proceso.stdout, tope),
                    _leer_recortado(proceso.stderr, tope),
                    proceso.wait(),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as agotado:
            proceso.kill()
            await proceso.wait()
            raise GuionFallido(
                f"El guion no terminó en {timeout} s y se ha detenido"
            ) from agotado

        if codigo_salida != 0:
            raise GuionFallido(
                _motivo(error) or f"El guion terminó con código {codigo_salida}"
            )
        if not salida.exists():
            raise GuionFallido("El guion terminó sin devolver ningún resultado")
        try:
            resultado = json.loads(salida.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as roto:
            raise GuionFallido("El resultado del guion no es JSON válido") from roto

    devuelto = {
        "herramienta": guion["id"],
        "version": int(guion["version"]),
        "resultado": resultado,
    }
    if impreso.strip():
        devuelto["salida"] = impreso.strip()[:tope]
    return devuelto


def _motivo(error: str) -> str:
    """La última línea de la traza, que es la que dice qué pasó."""
    lineas = [linea.strip() for linea in error.strip().splitlines() if linea.strip()]
    if not lineas:
        return ""
    if len(lineas) == 1:
        return lineas[-1][:400]
    return f"{lineas[-1]} (en {lineas[-2]})"[:400]


# ---------- catálogo ----------

def parametros_de(fila: dict) -> list[dict]:
    valor = fila["parametros"]
    return valor if isinstance(valor, list) else json.loads(valor)


def serializar(fila: dict, con_codigo: bool = False) -> dict:
    """La herramienta con la forma que espera el catálogo de `tools.py`."""
    parametros = parametros_de(fila)
    comprobacion = fila["comprobacion"]
    herramienta = {
        "id": fila["id"],
        "name": fila["name"],
        "description": fila["description"],
        "scope": "personal",
        "kind": "script",
        # No hay primitiva detrás: esto ejecuta su propio código. Va vacío y no
        # ausente porque el catálogo lo publica a la PWA y a los dos motores.
        "primitive_id": "",
        "permissions": ["tools:run:self"],
        "effects": ["script:run"],
        "input_schema": esquema_de(parametros),
        "parametros": parametros,
        "bound_arguments": {},
        "enabled": bool(fila["enabled"]),
        "source": "agent",
        "modelo": fila["modelo"],
        "peticion": fila["peticion"],
        "comprobacion": (
            comprobacion
            if isinstance(comprobacion, dict)
            else json.loads(comprobacion)
        ),
        "version": int(fila["version"]),
        "lineas": fila["codigo"].count("\n") + 1,
        "created_at": fila["created_at"],
        "updated_at": fila["updated_at"],
        # El editor de composiciones no sabe editar código, y duplicar un guion
        # sin cambiarle nada solo ensucia el catálogo: se rehace forjándolo.
        "editable": False,
        "duplicable": False,
    }
    if con_codigo:
        herramienta["codigo"] = fila["codigo"]
    return herramienta


def cargar(tool_id: str, user_id: str) -> dict | None:
    if not tool_id.startswith(PREFIJO):
        return None
    return db.get_tool_script(tool_id, user_id)


def listar(user_id: str) -> list[dict]:
    return db.list_tool_scripts(user_id)


def activar(tool_id: str, user_id: str, enabled: bool) -> dict | None:
    return db.set_tool_script_enabled(tool_id, user_id, enabled)


def _hueco(user_id: str, slug: str) -> tuple[str, str]:
    """El id libre para ese slug: `script.<slug>`, con sufijo si hace falta.

    El sufijo va en el slug y no solo en el id porque son la misma cosa vista
    de dos maneras, y separarlos deja al usuario con dos herramientas que se
    llaman igual.
    """
    candidato = slug
    sufijo = 2
    while db.get_tool_script(f"{PREFIJO}{candidato}", user_id):
        candidato = f"{slug}-{sufijo}"
        sufijo += 1
    return f"{PREFIJO}{candidato}", candidato


# ---------- forja ----------

async def _comprobar(manifiesto: dict, tool_id: str) -> dict:
    """Ejecuta el guion una vez con los argumentos de ejemplo del modelo.

    Es lo que separa una herramienta de un archivo de texto con pinta de
    código. Sin esto, el primer intento de usarla —días después, en mitad de
    otra conversación— sería también el primero en descubrir que no arranca.
    """
    prueba = manifiesto.get("prueba")
    if prueba is None:
        return {"estado": "omitida", "motivo": "No propusiste argumentos de prueba"}
    guion = {
        "id": tool_id,
        "version": 1,
        "codigo": manifiesto["codigo"],
    }
    try:
        argumentos = modelo_de(manifiesto["parametros"]).model_validate(prueba)
    except ValidationError as error:
        return {
            "estado": "fallo",
            "argumentos": prueba,
            "error": f"Los argumentos de prueba no valen: {error}",
        }
    inicio = time.monotonic()
    try:
        resultado = await ejecutar_guion(guion, argumentos.model_dump())
    except GuionFallido as error:
        return {"estado": "fallo", "argumentos": prueba, "error": str(error)}
    return {
        "estado": "ok",
        "argumentos": prueba,
        "ms": int((time.monotonic() - inicio) * 1000),
        "resultado": resultado["resultado"],
    }


async def forjar(user: dict, peticion: str, reemplaza: str | None = None) -> dict:
    """Encarga la herramienta a Claude, la prueba y la guarda si arranca."""
    from .executors import claude_forja  # noqa: PLC0415 - evita el ciclo con tools
    from . import tasks  # noqa: PLC0415 - idem

    limpia = (peticion or "").strip()
    if len(limpia) < 10:
        raise ManifiestoInvalido(
            "Explica con más detalle qué debe hacer la herramienta"
        )
    if len(limpia) > MAX_PETICION:
        raise ManifiestoInvalido(
            f"La petición supera los {MAX_PETICION} caracteres"
        )

    anterior = cargar(reemplaza, user["id"]) if reemplaza else None
    if reemplaza and not anterior:
        raise ManifiestoInvalido(f"No existe ninguna herramienta «{reemplaza}»")

    workspace = str(tasks.directorio_usuario(user["id"]))
    fallo = ""
    manifiesto: dict | None = None
    comprobacion: dict = {}
    intentos = 0
    for intentos in range(1, INTENTOS + 1):
        crudo = await claude_forja.escribir(
            user["id"],
            user["nombre"],
            workspace,
            limpia,
            anterior=anterior,
            fallo=fallo,
        )
        try:
            candidato = validar_manifiesto(objeto_json(crudo))
        except ManifiestoInvalido as error:
            # Se pierde el intento, no lo que ya se tenía: si uno anterior dio
            # un guion válido cuya prueba falló, ese sigue siendo mejor que
            # nada y acaba guardado desactivado. `manifiesto` y `comprobacion`
            # se asignan juntos más abajo, así que nunca se descasan.
            fallo = str(error)
            continue
        tentativo = anterior["id"] if anterior else f"{PREFIJO}{candidato['slug']}"
        comprobacion = await _comprobar(candidato, tentativo)
        manifiesto = candidato
        if comprobacion["estado"] != "fallo":
            break
        fallo = comprobacion["error"]

    if manifiesto is None:
        raise ForjaFallida(
            f"Claude no consiguió escribir un guion utilizable en {INTENTOS} "
            f"intentos. Lo último que falló: {fallo}"
        )

    activada = comprobacion.get("estado") != "fallo"
    if anterior:
        fila = db.update_tool_script(
            anterior["id"],
            user["id"],
            manifiesto["name"],
            manifiesto["description"],
            manifiesto["parametros"],
            manifiesto["codigo"],
            limpia,
            claude_forja.modelo(),
            comprobacion,
            activada,
        )
    else:
        tool_id, slug = _hueco(user["id"], manifiesto["slug"])
        fila = db.create_tool_script(
            tool_id,
            user["id"],
            slug,
            manifiesto["name"],
            manifiesto["description"],
            manifiesto["parametros"],
            manifiesto["codigo"],
            limpia,
            claude_forja.modelo(),
            comprobacion,
            activada,
        )

    db.log_event(
        "herramienta_forjada",
        user["id"],
        tool_id=fila["id"],
        modelo=claude_forja.modelo(),
        intentos=intentos,
        comprobacion=comprobacion.get("estado"),
        rehecha=bool(anterior),
    )
    return {
        "herramienta": serializar(fila),
        "comprobacion": comprobacion,
        "notas": manifiesto["notas"],
        "intentos": intentos,
        "aviso": (
            "Ya está guardada en el catálogo y disponible desde el próximo "
            "mensaje; en este turno todavía no puedes llamarla."
            if activada
            else "Se ha guardado desactivada porque la prueba falló: díselo "
            "al usuario con el error y ofrécele rehacerla."
        ),
    }
