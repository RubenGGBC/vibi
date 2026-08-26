# Especialización por usuario — Plan de implementación

> **Para agentes:** SUB-SKILL OBLIGATORIA: usa `superpowers:subagent-driven-development` (recomendado) o `superpowers:executing-plans` para ejecutar este plan tarea a tarea. Los pasos usan casillas (`- [ ]`) para el seguimiento.

**Objetivo:** Que cada instancia de Vibi acabe siendo distinta porque el usuario es distinto: una entrevista corta el primer día que arranca desde el estado real de la máquina, y un perfil que se corrige solo con el uso.

**Arquitectura:** Un perfil de afirmaciones con procedencia y confianza; un activador puro que traduce perfil a configuración (MCP, skills, vigilancias, `GEMINI.md`); y un observador que mueve las confianzas leyendo contadores que ya existen. El descubrimiento de capacidades se consume del registro oficial de MCP, no se reimplementa.

**Stack:** Python 3.11, FastAPI, SQLite (sin ORM), pytest. El nodo es Python sobre Windows.

**Spec:** `docs/superpowers/specs/2026-08-26-especializacion-por-usuario-design.md`

## Restricciones globales

- **Nada se instala sin aprobación explícita del usuario.** El sistema propone; la decisión es siempre suya.
- **El contenido de los archivos del usuario no sale del equipo sin permiso pedido en el momento.** El inventario manda un agregado construido en local.
- **Todo el código, los comentarios y los mensajes de error van en español**, siguiendo el estilo del repositorio: explicar el porqué, con el dato y la fecha cuando exista.
- **Los tests nunca tocan la base real.** `tests/conftest.py` ya redirige `settings.db_path` a `%TEMP%/vibi-tests/vibi.db`. No hay que añadir nada, pero tampoco crear conexiones por fuera de `db._conn()`.
- **Acceso a datos con `db._conn()`**, siguiendo el patrón de `app/recetas.py`, no las funciones sueltas de `db.py`.
- **Ninguna prueba depende de la red.** El registro se prueba contra respuestas grabadas.
- Umbrales de confianza (valores de partida, definidos en la spec): entrevista 0,6 · inventario 0,4 · uso 0,8 · apoyo +0,10 · contradicción −0,30 · decaimiento −0,05 · `completo` ≥ 0,6 · `catalogo` ≥ 0,3 · `propuesta_retirada` < 0,3.

---

## Fase 0 — Lo que hay que saber antes de escribir código

### Tarea 0: Spike de lectura de PDF por el motor

**Por qué primero:** el nivel 3 de la entrevista asume que el modelo puede leer un PDF. Está verificado que `agy` reenvía al modelo el `ImageContent` de una tool MCP (10/08/2026, `devices.screenshot`), pero **un PDF no es `ImageContent`**. Si no se puede, el nivel 3 cambia de diseño.

**Archivos:**
- Crear: `docs/spikes/2026-08-26-pdf-multimodal.md` (hallazgos)

- [ ] **Paso 1: Preparar un PDF de prueba con un dato verificable**

Crea un PDF de una página que contenga un código aleatorio que no exista en ningún otro sitio (por ejemplo `NARANJA-7741`). El dato aleatorio es lo que distingue «lo ha leído» de «se lo ha imaginado».

- [ ] **Paso 2: Probar la vía de extracción de texto**

Extrae el texto con lo que ya haya disponible en el entorno y pásalo como texto plano en el turno. Anota si el modelo recita el código.

- [ ] **Paso 3: Probar la vía de imagen**

Convierte la primera página a PNG y devuélvela como `ImageContent` desde una tool MCP, igual que hace `devices.screenshot`. Anota si el modelo recita el código.

- [ ] **Paso 4: Escribir los hallazgos**

Documenta qué vía funciona, cuánto tarda cada una y cuántos tokens cuesta. Si ninguna funciona, escríbelo igual: es un resultado.

- [ ] **Paso 5: Commit**

```bash
git add docs/spikes/2026-08-26-pdf-multimodal.md
git commit -m "docs: spike de lectura de PDF por el motor"
```

---

## Fase 1 — El perfil

### Tarea 1: Tablas y afirmaciones

**Archivos:**
- Crear: `app/perfil.py`
- Modificar: `app/db.py` (llamar a `perfil.crear_tablas()` desde `init_db`)
- Test: `tests/test_perfil.py`

**Interfaces:**
- Consume: `db._conn()`
- Produce: `crear_tablas()`, `afirmar(user_id, clase, valor, procedencia) -> dict`, `afirmaciones_de(user_id, clase=None) -> list[dict]`, `CONFIANZA_INICIAL: dict[str, float]`, `CLASES: frozenset`, `PROCEDENCIAS: frozenset`, excepción `PerfilInvalido`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_perfil.py
import pytest
from app import perfil

def test_afirmar_guarda_con_la_confianza_de_su_procedencia():
    perfil.crear_tablas()
    hecho = perfil.afirmar("u1", "dominio", "medicina", "entrevista")
    assert hecho["valor"] == "medicina"
    assert hecho["confianza"] == pytest.approx(0.6)

def test_el_inventario_entra_con_menos_confianza_que_la_entrevista():
    perfil.crear_tablas()
    perfil.afirmar("u1", "dominio", "medicina", "inventario")
    guardada = perfil.afirmaciones_de("u1")[0]
    assert guardada["confianza"] == pytest.approx(0.4)

def test_afirmar_dos_veces_lo_mismo_no_duplica():
    perfil.crear_tablas()
    perfil.afirmar("u1", "dominio", "medicina", "inventario")
    perfil.afirmar("u1", "dominio", "medicina", "entrevista")
    assert len(perfil.afirmaciones_de("u1")) == 1

def test_una_clase_desconocida_es_un_error():
    perfil.crear_tablas()
    with pytest.raises(perfil.PerfilInvalido):
        perfil.afirmar("u1", "signo-zodiacal", "acuario", "entrevista")
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_perfil.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'app.perfil'`

- [ ] **Paso 3: Implementación mínima**

```python
# app/perfil.py
"""Lo que Vibi cree saber de quién tiene delante.

**Una afirmación no es un dato, es una hipótesis.** «Estudia medicina» puede
venir de que lo dijo en la entrevista, de que tiene una carpeta llamada
Farmacología, o de que lleva un mes abriendo PDF de ese tema. Las tres cosas
no valen lo mismo, y por eso cada afirmación guarda **de dónde salió** y
**cuánta confianza tiene**.

Es la disciplina de `recetas.py` —solo lo verificado vale— aplicada al perfil,
con una diferencia deliberada: una receta mala hace fallar la tarea y por eso
se retira sola; una afirmación floja solo hace que sobre una herramienta, así
que baja de nivel y la retirada se propone.
"""
from __future__ import annotations

import time

from . import db

CLASES = frozenset({"dominio", "herramienta", "preferencia", "aficion"})
PROCEDENCIAS = frozenset({"entrevista", "inventario", "uso"})

# Con cuánta confianza nace una afirmación según quién la trajo. El uso pesa
# más que lo declarado porque lo que alguien hace dice más que lo que dice que
# hace; el inventario pesa menos porque una carpeta llamada «Bioquímica» puede
# ser de otra persona.
CONFIANZA_INICIAL = {"entrevista": 0.6, "inventario": 0.4, "uso": 0.8}


class PerfilError(Exception):
    """Algo que impide guardar o mover el perfil."""


class PerfilInvalido(PerfilError):
    pass


def crear_tablas() -> None:
    with db._conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS perfil (
            user_id      TEXT PRIMARY KEY,
            resumen      TEXT NOT NULL DEFAULT '',
            creado_en    REAL NOT NULL,
            revisado_en  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS perfil_afirmaciones (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT NOT NULL,
            clase        TEXT NOT NULL,
            valor        TEXT NOT NULL,
            procedencia  TEXT NOT NULL,
            confianza    REAL NOT NULL,
            apoyos       INTEGER NOT NULL DEFAULT 0,
            contras      INTEGER NOT NULL DEFAULT 0,
            creada_en    REAL NOT NULL,
            movida_en    REAL NOT NULL,
            UNIQUE(user_id, clase, valor)
        );
        """)


def _normalizar(valor: object) -> str:
    return " ".join(str(valor or "").split()).casefold()


def afirmar(user_id: str, clase: str, valor: object, procedencia: str) -> dict:
    """Apunta algo que se cree del usuario, con quién lo trajo.

    Si ya estaba, **no se duplica ni se pisa la confianza acumulada**: solo se
    anota la procedencia más fuerte. Una afirmación que ya llevaba semanas
    sosteniéndose con el uso no vuelve a 0,6 porque alguien la repita en una
    entrevista.
    """
    if clase not in CLASES:
        raise PerfilInvalido(
            f"«{clase}» no es una clase de afirmación; son {', '.join(sorted(CLASES))}"
        )
    if procedencia not in PROCEDENCIAS:
        raise PerfilInvalido(
            f"«{procedencia}» no es una procedencia; son {', '.join(sorted(PROCEDENCIAS))}"
        )
    texto = _normalizar(valor)
    if not texto:
        raise PerfilInvalido("Una afirmación vacía no dice nada del usuario")

    ahora = time.time()
    inicial = CONFIANZA_INICIAL[procedencia]
    with db._conn() as c:
        fila = c.execute(
            "SELECT * FROM perfil_afirmaciones WHERE user_id=? AND clase=? AND valor=?",
            (user_id, clase, texto),
        ).fetchone()
        if fila:
            if inicial > fila["confianza"]:
                c.execute(
                    "UPDATE perfil_afirmaciones SET procedencia=?, confianza=?, movida_en=? WHERE id=?",
                    (procedencia, inicial, ahora, fila["id"]),
                )
        else:
            c.execute(
                """INSERT INTO perfil_afirmaciones
                   (user_id, clase, valor, procedencia, confianza, creada_en, movida_en)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, clase, texto, procedencia, inicial, ahora, ahora),
            )
    return [a for a in afirmaciones_de(user_id, clase) if a["valor"] == texto][0]


def afirmaciones_de(user_id: str, clase: str | None = None) -> list[dict]:
    consulta = "SELECT * FROM perfil_afirmaciones WHERE user_id=?"
    parametros: list = [user_id]
    if clase:
        consulta += " AND clase=?"
        parametros.append(clase)
    with db._conn() as c:
        return [dict(f) for f in c.execute(consulta + " ORDER BY id", parametros)]
```

Y en `app/db.py`, dentro de `init_db()`, añade al final:

```python
    from . import perfil  # noqa: PLC0415 - perezoso para no cerrar un ciclo
    perfil.crear_tablas()
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_perfil.py -v`
Esperado: PASS, los cuatro tests.

- [ ] **Paso 5: Commit**

```bash
git add app/perfil.py app/db.py tests/test_perfil.py
git commit -m "feat(perfil): afirmaciones con procedencia y confianza"
```

---

### Tarea 2: El movimiento de la confianza

**Archivos:**
- Modificar: `app/perfil.py`
- Test: `tests/test_perfil.py`

**Interfaces:**
- Consume: `afirmar()`, `afirmaciones_de()` de la Tarea 1
- Produce: `apoyar(user_id, clase, valor) -> None`, `contradecir(user_id, clase, valor) -> None`, `decaer(user_id, sin_uso: list[tuple[str, str]]) -> None`, constantes `APOYO`, `CONTRADICCION`, `DECAIMIENTO`

- [ ] **Paso 1: Escribir el test que falla**

```python
def test_el_uso_sube_la_confianza_y_cuenta_el_apoyo():
    perfil.crear_tablas()
    perfil.afirmar("u2", "dominio", "medicina", "inventario")
    perfil.apoyar("u2", "dominio", "medicina")
    a = perfil.afirmaciones_de("u2")[0]
    assert a["confianza"] == pytest.approx(0.5)
    assert a["apoyos"] == 1

def test_la_confianza_no_pasa_de_uno():
    perfil.crear_tablas()
    perfil.afirmar("u3", "dominio", "medicina", "uso")
    for _ in range(10):
        perfil.apoyar("u3", "dominio", "medicina")
    assert perfil.afirmaciones_de("u3")[0]["confianza"] == pytest.approx(1.0)

def test_la_contradiccion_pesa_tres_veces_mas_que_un_apoyo():
    perfil.crear_tablas()
    perfil.afirmar("u4", "dominio", "medicina", "entrevista")
    perfil.contradecir("u4", "dominio", "medicina")
    a = perfil.afirmaciones_de("u4")[0]
    assert a["confianza"] == pytest.approx(0.3)
    assert a["contras"] == 1

def test_la_confianza_no_baja_de_cero():
    perfil.crear_tablas()
    perfil.afirmar("u5", "dominio", "medicina", "inventario")
    for _ in range(5):
        perfil.contradecir("u5", "dominio", "medicina")
    assert perfil.afirmaciones_de("u5")[0]["confianza"] == pytest.approx(0.0)

def test_decaer_solo_toca_lo_que_no_se_ha_usado():
    perfil.crear_tablas()
    perfil.afirmar("u6", "dominio", "medicina", "entrevista")
    perfil.afirmar("u6", "dominio", "musica", "entrevista")
    perfil.decaer("u6", sin_uso=[("dominio", "musica")])
    por_valor = {a["valor"]: a["confianza"] for a in perfil.afirmaciones_de("u6")}
    assert por_valor["medicina"] == pytest.approx(0.6)
    assert por_valor["musica"] == pytest.approx(0.55)
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_perfil.py -v -k "confianza or apoyo or decaer or contradiccion"`
Esperado: FAIL con `AttributeError: module 'app.perfil' has no attribute 'apoyar'`

- [ ] **Paso 3: Implementación mínima**

Añade a `app/perfil.py`:

```python
# Cuánto se mueve la confianza en cada dirección. La contradicción pesa el
# triple que un apoyo a propósito: acertar una vez puede ser casualidad, pero
# que el usuario haga justo lo contrario de lo que se creía es información.
APOYO = 0.10
CONTRADICCION = 0.30
# Y lo que se pierde por no aparecer en una revisión entera. Va despacio
# porque hay cosas que se hacen una vez al mes y siguen importando.
DECAIMIENTO = 0.05


def _mover(user_id: str, clase: str, valor: object, delta: float, campo: str | None) -> None:
    texto = _normalizar(valor)
    ahora = time.time()
    with db._conn() as c:
        fila = c.execute(
            "SELECT * FROM perfil_afirmaciones WHERE user_id=? AND clase=? AND valor=?",
            (user_id, clase, texto),
        ).fetchone()
        if not fila:
            return
        nueva = min(1.0, max(0.0, fila["confianza"] + delta))
        if campo:
            c.execute(
                f"UPDATE perfil_afirmaciones SET confianza=?, {campo}={campo}+1, movida_en=? WHERE id=?",
                (nueva, ahora, fila["id"]),
            )
        else:
            c.execute(
                "UPDATE perfil_afirmaciones SET confianza=?, movida_en=? WHERE id=?",
                (nueva, ahora, fila["id"]),
            )


def apoyar(user_id: str, clase: str, valor: object) -> None:
    """El uso ha confirmado esto."""
    _mover(user_id, clase, valor, APOYO, "apoyos")


def contradecir(user_id: str, clase: str, valor: object) -> None:
    """El uso dice lo contrario de esto."""
    _mover(user_id, clase, valor, -CONTRADICCION, "contras")


def decaer(user_id: str, sin_uso: list[tuple[str, str]]) -> None:
    """Lo que no ha aparecido en toda la revisión pierde un poco de fuerza."""
    for clase, valor in sin_uso:
        _mover(user_id, clase, valor, -DECAIMIENTO, None)
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_perfil.py -v`
Esperado: PASS, los nueve tests.

- [ ] **Paso 5: Commit**

```bash
git add app/perfil.py tests/test_perfil.py
git commit -m "feat(perfil): apoyo, contradiccion y decaimiento de la confianza"
```

---

### Tarea 3: Capacidades y niveles

**Archivos:**
- Modificar: `app/perfil.py`
- Test: `tests/test_perfil_capacidades.py`

**Interfaces:**
- Consume: `crear_tablas()`, `db._conn()`
- Produce: `aprobar_capacidad(user_id, tipo, referencia, justificacion, transporte="") -> dict`, `capacidades_de(user_id, tipo=None) -> list[dict]`, `registrar_uso_capacidad(user_id, tipo, referencia) -> None`, `nivel_para(confianza: float) -> str`, `TIPOS`, `NIVELES`, `UMBRAL_COMPLETO`, `UMBRAL_CATALOGO`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_perfil_capacidades.py
import pytest
from app import perfil

def test_nivel_por_umbral():
    assert perfil.nivel_para(0.9) == "completo"
    assert perfil.nivel_para(0.6) == "completo"
    assert perfil.nivel_para(0.45) == "catalogo"
    assert perfil.nivel_para(0.3) == "catalogo"
    assert perfil.nivel_para(0.1) == "propuesta_retirada"

def test_aprobar_capacidad_la_deja_completa_y_sin_usos():
    perfil.crear_tablas()
    cap = perfil.aprobar_capacidad(
        "u1", "mcp", "ai.pdfassistant/pdfassistant",
        "Lee y convierte los PDF de tus apuntes", transporte="remoto",
    )
    assert cap["nivel"] == "completo"
    assert cap["usos"] == 0
    assert cap["aprobada_en"] is not None

def test_registrar_uso_cuenta_y_marca_la_fecha():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("u2", "skill", "resumir-paper", "Resume papers")
    perfil.registrar_uso_capacidad("u2", "skill", "resumir-paper")
    cap = perfil.capacidades_de("u2")[0]
    assert cap["usos"] == 1
    assert cap["ultimo_uso"] is not None

def test_un_tipo_desconocido_es_un_error():
    perfil.crear_tablas()
    with pytest.raises(perfil.PerfilInvalido):
        perfil.aprobar_capacidad("u3", "plugin", "lo-que-sea", "porque si")

def test_una_capacidad_sin_justificacion_es_un_error():
    perfil.crear_tablas()
    with pytest.raises(perfil.PerfilInvalido):
        perfil.aprobar_capacidad("u4", "mcp", "algo/algo", "")
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_perfil_capacidades.py -v`
Esperado: FAIL con `AttributeError: module 'app.perfil' has no attribute 'nivel_para'`

- [ ] **Paso 3: Implementación mínima**

Añade a `app/perfil.py` (y la tabla dentro de `crear_tablas()`):

```python
TIPOS = frozenset({"mcp", "skill", "vigilancia"})
NIVELES = ("completo", "catalogo", "propuesta_retirada")

# A partir de dónde una capacidad entra entera en el contexto, y a partir de
# dónde solo se recuerda. No es un capricho: cada servidor MCP declarado mete
# sus esquemas en todos los turnos, y por eso el catálogo de `agy` bajó de 97
# a 65 esquemas cuando se podó.
UMBRAL_COMPLETO = 0.6
UMBRAL_CATALOGO = 0.3


def nivel_para(confianza: float) -> str:
    if confianza >= UMBRAL_COMPLETO:
        return "completo"
    if confianza >= UMBRAL_CATALOGO:
        return "catalogo"
    return "propuesta_retirada"


def aprobar_capacidad(
    user_id: str,
    tipo: str,
    referencia: str,
    justificacion: str,
    transporte: str = "",
) -> dict:
    """El usuario ha dicho que sí a esto.

    `justificacion` no admite vacío: es lo que se le enseña el día que se le
    proponga retirarla, y sin ella la propuesta es «quita esto porque sí».
    """
    if tipo not in TIPOS:
        raise PerfilInvalido(
            f"«{tipo}» no es un tipo de capacidad; son {', '.join(sorted(TIPOS))}"
        )
    if transporte not in ("", "remoto", "local"):
        raise PerfilInvalido(f"«{transporte}» no es un transporte conocido")
    motivo = str(justificacion or "").strip()
    if not motivo:
        raise PerfilInvalido("Una capacidad sin justificación no se puede revisar después")

    ahora = time.time()
    with db._conn() as c:
        c.execute(
            """INSERT INTO perfil_capacidades
               (user_id, tipo, referencia, justificacion, transporte, nivel, aprobada_en)
               VALUES (?, ?, ?, ?, ?, 'completo', ?)
               ON CONFLICT(user_id, tipo, referencia) DO UPDATE SET
                   justificacion = excluded.justificacion,
                   transporte = excluded.transporte,
                   nivel = 'completo',
                   aprobada_en = excluded.aprobada_en""",
            (user_id, tipo, referencia, motivo, transporte, ahora),
        )
    return [
        cap for cap in capacidades_de(user_id, tipo) if cap["referencia"] == referencia
    ][0]


def capacidades_de(user_id: str, tipo: str | None = None) -> list[dict]:
    consulta = "SELECT * FROM perfil_capacidades WHERE user_id=?"
    parametros: list = [user_id]
    if tipo:
        consulta += " AND tipo=?"
        parametros.append(tipo)
    with db._conn() as c:
        return [dict(f) for f in c.execute(consulta + " ORDER BY id", parametros)]


def registrar_uso_capacidad(user_id: str, tipo: str, referencia: str) -> None:
    with db._conn() as c:
        c.execute(
            """UPDATE perfil_capacidades SET usos = usos + 1, ultimo_uso = ?
               WHERE user_id=? AND tipo=? AND referencia=?""",
            (time.time(), user_id, tipo, referencia),
        )


def fijar_nivel(user_id: str, tipo: str, referencia: str, nivel: str) -> None:
    if nivel not in NIVELES:
        raise PerfilInvalido(f"«{nivel}» no es un nivel; son {', '.join(NIVELES)}")
    with db._conn() as c:
        c.execute(
            "UPDATE perfil_capacidades SET nivel=? WHERE user_id=? AND tipo=? AND referencia=?",
            (nivel, user_id, tipo, referencia),
        )
```

Y dentro del `executescript` de `crear_tablas()`:

```sql
        CREATE TABLE IF NOT EXISTS perfil_capacidades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL,
            tipo          TEXT NOT NULL,
            referencia    TEXT NOT NULL,
            justificacion TEXT NOT NULL,
            transporte    TEXT NOT NULL DEFAULT '',
            nivel         TEXT NOT NULL DEFAULT 'completo',
            aprobada_en   REAL,
            usos          INTEGER NOT NULL DEFAULT 0,
            ultimo_uso    REAL,
            UNIQUE(user_id, tipo, referencia)
        );
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_perfil_capacidades.py -v`
Esperado: PASS, los cinco tests.

- [ ] **Paso 5: Commit**

```bash
git add app/perfil.py tests/test_perfil_capacidades.py
git commit -m "feat(perfil): capacidades aprobadas con nivel por confianza"
```

---

## Fase 2 — El activador

### Tarea 4: La función pura perfil → configuración

**Archivos:**
- Crear: `app/perfil_activador.py`
- Test: `tests/test_perfil_activador.py`

**Interfaces:**
- Consume: nada del sistema. Recibe listas de diccionarios, no toca base de datos ni red.
- Produce: `Configuracion` (dataclass con `mcp: tuple[str, ...]`, `skills_completas: tuple[str, ...]`, `skills_catalogo: tuple[str, ...]`, `vigilancias_activas: tuple[str, ...]`, `resumen: str`) y `decidir(afirmaciones, capacidades) -> Configuracion`

**Por qué es puro:** para que la ablación del experimento sea un parámetro y no una rama de código. Pasarle un perfil vacío es el grupo de control.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_perfil_activador.py
from app import perfil_activador as activador

def cap(tipo, ref, nivel="completo"):
    return {"tipo": tipo, "referencia": ref, "nivel": nivel, "justificacion": "x"}

def test_solo_los_mcp_completos_llegan_al_motor():
    conf = activador.decidir(
        afirmaciones=[],
        capacidades=[cap("mcp", "a/uno"), cap("mcp", "b/dos", nivel="catalogo")],
    )
    assert conf.mcp == ("a/uno",)

def test_las_skills_de_catalogo_siguen_visibles_pero_aparte():
    conf = activador.decidir(
        afirmaciones=[],
        capacidades=[cap("skill", "resumir"), cap("skill", "citar", nivel="catalogo")],
    )
    assert conf.skills_completas == ("resumir",)
    assert conf.skills_catalogo == ("citar",)

def test_una_capacidad_propuesta_para_retirada_no_se_activa_de_ninguna_forma():
    conf = activador.decidir(
        afirmaciones=[],
        capacidades=[cap("mcp", "c/tres", nivel="propuesta_retirada"),
                     cap("skill", "vieja", nivel="propuesta_retirada"),
                     cap("vigilancia", "v1", nivel="propuesta_retirada")],
    )
    assert conf.mcp == ()
    assert conf.skills_completas == ()
    assert conf.skills_catalogo == ()
    assert conf.vigilancias_activas == ()

def test_el_resumen_solo_recoge_lo_que_se_sostiene():
    conf = activador.decidir(
        afirmaciones=[
            {"clase": "dominio", "valor": "medicina", "confianza": 0.8},
            {"clase": "aficion", "valor": "ciclismo", "confianza": 0.2},
        ],
        capacidades=[],
    )
    assert "medicina" in conf.resumen
    assert "ciclismo" not in conf.resumen

def test_un_perfil_vacio_da_una_configuracion_vacia():
    conf = activador.decidir(afirmaciones=[], capacidades=[])
    assert conf == activador.Configuracion((), (), (), (), "")
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_perfil_activador.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'app.perfil_activador'`

- [ ] **Paso 3: Implementación mínima**

```python
# app/perfil_activador.py
"""Traducir lo que se cree del usuario a lo que el sistema enciende.

**Esto no toca nada.** Entra un perfil, sale una configuración; quien la
aplique es otro. Es una decisión de diseño y no de estilo: si activar fuera un
efecto suelto por el código, comparar «Vibi con perfil» contra «Vibi sin
perfil» exigiría dos ramas. Siendo una función pura, el grupo de control del
experimento es pasarle una lista vacía.

Y el nivel intermedio no significa lo mismo para todo, porque el transporte no
da para más: una skill puede entrar a medias —solo nombre y descripción— pero
un servidor MCP declarado expone todas sus herramientas o no está.
"""
from __future__ import annotations

from dataclasses import dataclass

# Por debajo de esto una afirmación no se le cuenta al modelo. No es el mismo
# umbral que el de las capacidades: aquí solo se decide qué se dice de ti en
# el resumen, y decir algo flojo es peor que callarlo.
MINIMO_PARA_CONTAR = 0.5


@dataclass(frozen=True)
class Configuracion:
    mcp: tuple[str, ...]
    skills_completas: tuple[str, ...]
    skills_catalogo: tuple[str, ...]
    vigilancias_activas: tuple[str, ...]
    resumen: str


def _referencias(capacidades: list[dict], tipo: str, nivel: str) -> tuple[str, ...]:
    return tuple(
        c["referencia"]
        for c in capacidades
        if c["tipo"] == tipo and c["nivel"] == nivel
    )


def _redactar(afirmaciones: list[dict]) -> str:
    """Las afirmaciones que se sostienen, en frases cortas para `GEMINI.md`."""
    encabezados = {
        "dominio": "Se dedica a",
        "herramienta": "Trabaja con",
        "preferencia": "Prefiere",
        "aficion": "Le interesa",
    }
    lineas = []
    for clase, encabezado in encabezados.items():
        valores = [
            a["valor"]
            for a in afirmaciones
            if a["clase"] == clase and a["confianza"] >= MINIMO_PARA_CONTAR
        ]
        if valores:
            lineas.append(f"{encabezado}: {', '.join(valores)}.")
    return "\n".join(lineas)


def decidir(afirmaciones: list[dict], capacidades: list[dict]) -> Configuracion:
    return Configuracion(
        mcp=_referencias(capacidades, "mcp", "completo"),
        skills_completas=_referencias(capacidades, "skill", "completo"),
        skills_catalogo=_referencias(capacidades, "skill", "catalogo"),
        vigilancias_activas=_referencias(capacidades, "vigilancia", "completo"),
        resumen=_redactar(afirmaciones),
    )
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_perfil_activador.py -v`
Esperado: PASS, los cinco tests.

- [ ] **Paso 5: Commit**

```bash
git add app/perfil_activador.py tests/test_perfil_activador.py
git commit -m "feat(perfil): activador puro de perfil a configuracion"
```

---

## Fase 3 — El registro de capacidades

### Tarea 5: Cliente del registro oficial de MCP

**Archivos:**
- Crear: `app/registro_mcp.py`
- Test: `tests/test_registro_mcp.py`

**Interfaces:**
- Consume: `httpx` (ya en el proyecto)
- Produce: `Servidor` (dataclass: `nombre`, `titulo`, `descripcion`, `version`, `web`, `transporte`, `activo`), `interpretar(payload: dict) -> list[Servidor]`, `buscar(termino: str, limite: int = 10) -> list[Servidor]`, `URL_REGISTRO`

**Formato real de la respuesta**, verificado el 26/08/2026 contra `https://registry.modelcontextprotocol.io/v0/servers?search=pdf`:

```json
{"servers": [{"server": {"name": "ai.pdfassistant/pdfassistant",
  "description": "Convert, merge, compress, OCR...", "title": "pdfAssistant",
  "version": "1.35.17", "websiteUrl": "https://pdfassistant.ai",
  "remotes": [{"type": "streamable-http", "url": "https://chat.pdfassistant.ai/mcp"}]},
  "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active"}}}]}
```

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_registro_mcp.py
from app import registro_mcp

RESPUESTA = {
    "servers": [
        {
            "server": {
                "name": "ai.pdfassistant/pdfassistant",
                "title": "pdfAssistant",
                "description": "Convert, merge, compress, OCR PDFs",
                "version": "1.35.17",
                "websiteUrl": "https://pdfassistant.ai",
                "remotes": [{"type": "streamable-http", "url": "https://chat.pdfassistant.ai/mcp"}],
            },
            "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active"}},
        },
        {
            "server": {
                "name": "cloud.massdriver/mcp-server",
                "title": "Massdriver",
                "description": "Infra",
                "version": "1.0.0",
                "packages": [{"registryType": "oci"}],
            },
            "_meta": {"io.modelcontextprotocol.registry/official": {"status": "deleted"}},
        },
    ]
}

def test_interpretar_distingue_remoto_de_local():
    servidores = registro_mcp.interpretar(RESPUESTA)
    por_nombre = {s.nombre: s for s in servidores}
    assert por_nombre["ai.pdfassistant/pdfassistant"].transporte == "remoto"
    assert por_nombre["cloud.massdriver/mcp-server"].transporte == "local"

def test_interpretar_marca_los_que_no_estan_activos():
    por_nombre = {s.nombre: s for s in registro_mcp.interpretar(RESPUESTA)}
    assert por_nombre["ai.pdfassistant/pdfassistant"].activo is True
    assert por_nombre["cloud.massdriver/mcp-server"].activo is False

def test_un_servidor_sin_transporte_no_se_devuelve():
    payload = {"servers": [{"server": {"name": "x/y", "description": "d", "version": "1"},
                            "_meta": {}}]}
    assert registro_mcp.interpretar(payload) == []

def test_una_respuesta_rota_no_revienta():
    assert registro_mcp.interpretar({}) == []
    assert registro_mcp.interpretar({"servers": None}) == []
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_registro_mcp.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'app.registro_mcp'`

- [ ] **Paso 3: Implementación mínima**

```python
# app/registro_mcp.py
"""El catálogo público de servidores MCP.

Descubrir capacidades ya es un servicio resuelto —el registro oficial expone
una API REST, y MCPfinder agrega además Glama y Smithery—, así que aquí no se
reimplementa nada: se consume. Lo que Vibi aporta está una capa más arriba,
en decidir **qué de todo esto encaja con quien pregunta**.

**El transporte no es un detalle, es la frontera de seguridad.** Un servidor
`remoto` no ejecuta nada en esta máquina pero se lleva los datos fuera; uno
`local` no manda nada fuera pero corre código de un tercero aquí dentro. Son
dos riesgos distintos y el usuario tiene que poder verlos separados antes de
aprobar.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("vibi.registro_mcp")

URL_REGISTRO = "https://registry.modelcontextprotocol.io/v0/servers"

# Cuánto se espera al registro. Es una consulta de conveniencia dentro de una
# entrevista: si tarda más que esto, se sigue sin propuesta antes que dejar al
# usuario mirando una pantalla parada.
ESPERA = 10.0

CLAVE_META = "io.modelcontextprotocol.registry/official"


@dataclass(frozen=True)
class Servidor:
    nombre: str
    titulo: str
    descripcion: str
    version: str
    web: str
    transporte: str
    activo: bool


def interpretar(payload: object) -> list[Servidor]:
    """Del JSON del registro a lo que aquí se usa, tolerando que cambie.

    El registro versiona su esquema y se actualiza sin avisarnos. Un campo que
    falte no puede tumbar una entrevista, así que todo se lee a la defensiva y
    lo que no se entiende se descarta en silencio.
    """
    if not isinstance(payload, dict):
        return []
    entradas = payload.get("servers")
    if not isinstance(entradas, list):
        return []

    servidores: list[Servidor] = []
    for entrada in entradas:
        if not isinstance(entrada, dict):
            continue
        bruto = entrada.get("server")
        if not isinstance(bruto, dict) or not bruto.get("name"):
            continue

        if bruto.get("remotes"):
            transporte = "remoto"
        elif bruto.get("packages"):
            transporte = "local"
        else:
            # Sin transporte no hay forma de arrancarlo ni de llamarlo, así
            # que proponerlo sería proponer un nombre.
            continue

        meta = entrada.get("_meta") or {}
        oficial = meta.get(CLAVE_META) or {}
        servidores.append(
            Servidor(
                nombre=str(bruto["name"]),
                titulo=str(bruto.get("title") or bruto["name"]),
                descripcion=str(bruto.get("description") or ""),
                version=str(bruto.get("version") or ""),
                web=str(bruto.get("websiteUrl") or ""),
                transporte=transporte,
                activo=oficial.get("status") == "active",
            )
        )
    return servidores


def buscar(termino: str, limite: int = 10) -> list[Servidor]:
    """Lo que el registro tenga para ese término, o nada si no contesta."""
    try:
        respuesta = httpx.get(
            URL_REGISTRO,
            params={"search": termino, "limit": limite},
            timeout=ESPERA,
        )
        respuesta.raise_for_status()
    except Exception as error:  # noqa: BLE001 - cualquier fallo es «sin propuesta»
        log.warning("El registro MCP no contestó a «%s»: %s", termino, error)
        return []
    return [s for s in interpretar(respuesta.json()) if s.activo]
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_registro_mcp.py -v`
Esperado: PASS, los cuatro tests.

- [ ] **Paso 5: Commit**

```bash
git add app/registro_mcp.py tests/test_registro_mcp.py
git commit -m "feat(registro): cliente del registro oficial de MCP"
```

---

### Tarea 6: Verificación antes de proponer

**Archivos:**
- Modificar: `app/registro_mcp.py`
- Test: `tests/test_registro_mcp.py`

**Interfaces:**
- Consume: `Servidor` de la Tarea 5
- Produce: `verificar(servidor: Servidor, sonda=None) -> tuple[bool, str]`

**Por qué:** es la regla de `RecetaNoVerificada` aplicada aquí. Proponer lo no comprobado empeora el sistema, porque el usuario aprueba confiando en que se miró.

- [ ] **Paso 1: Escribir el test que falla**

```python
def test_un_servidor_inactivo_no_pasa_la_verificacion():
    s = registro_mcp.Servidor("a/b", "A", "d", "1", "", "remoto", activo=False)
    vale, motivo = registro_mcp.verificar(s, sonda=lambda _: True)
    assert vale is False
    assert "activo" in motivo

def test_un_servidor_que_no_responde_no_pasa():
    s = registro_mcp.Servidor("a/b", "A", "d", "1", "", "remoto", activo=True)
    vale, motivo = registro_mcp.verificar(s, sonda=lambda _: False)
    assert vale is False
    assert "responde" in motivo

def test_un_servidor_activo_que_responde_pasa():
    s = registro_mcp.Servidor("a/b", "A", "d", "1", "", "remoto", activo=True)
    vale, motivo = registro_mcp.verificar(s, sonda=lambda _: True)
    assert vale is True
    assert motivo == ""

def test_la_sonda_que_revienta_cuenta_como_no_responde():
    def sonda_rota(_):
        raise RuntimeError("boom")
    s = registro_mcp.Servidor("a/b", "A", "d", "1", "", "local", activo=True)
    vale, _ = registro_mcp.verificar(s, sonda=sonda_rota)
    assert vale is False
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_registro_mcp.py -v -k verificacion or responde`
Esperado: FAIL con `AttributeError: module 'app.registro_mcp' has no attribute 'verificar'`

- [ ] **Paso 3: Implementación mínima**

```python
def _sonda_por_defecto(servidor: Servidor) -> bool:
    """Comprobar que existe algo al otro lado, sin instalarlo.

    De momento solo se sondean los remotos, que es una petición HTTP. Los
    locales exigirían descargar el paquete y arrancarlo, y eso ya no es una
    comprobación: es la instalación, que solo puede pasar después de que el
    usuario diga que sí.
    """
    if servidor.transporte != "remoto":
        return True
    if not servidor.web:
        return False
    try:
        respuesta = httpx.head(servidor.web, timeout=ESPERA, follow_redirects=True)
        return respuesta.status_code < 500
    except Exception:  # noqa: BLE001
        return False


def verificar(servidor: Servidor, sonda=None) -> tuple[bool, str]:
    """¿Se le puede proponer esto al usuario? Y si no, por qué no."""
    if not servidor.activo:
        return False, "no está activo en el registro oficial"
    comprobar = sonda or _sonda_por_defecto
    try:
        if not comprobar(servidor):
            return False, "no responde"
    except Exception as error:  # noqa: BLE001
        log.warning("La sonda de %s falló: %s", servidor.nombre, error)
        return False, "no responde"
    return True, ""
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_registro_mcp.py -v`
Esperado: PASS, los ocho tests.

- [ ] **Paso 5: Commit**

```bash
git add app/registro_mcp.py tests/test_registro_mcp.py
git commit -m "feat(registro): verificar un servidor antes de proponerlo"
```

---

## Fase 4 — La entrevista

### Tarea 7: El mapa agregado del disco, en el nodo

**Archivos:**
- Crear: `agent/vibi_node/inventario.py`
- Modificar: `agent/vibi_node/capabilities.py` (declarar la capacidad `inventario.mapa`)
- Test: `agent/tests/test_inventario.py`

**Interfaces:**
- Consume: `app_catalog.discover_windows_apps()`, `pathlib`
- Produce: `mapa_de(raices: list[Path], tope_carpetas: int = 25) -> dict` con la forma `{"carpetas": [{"ruta", "extensiones": {"pdf": 41}, "tocada_hace_dias": 2}], "apps": ["..."]}`

**Restricción crítica:** este agregado se construye **en el equipo** y es lo único que viaja. Ni un nombre de archivo, ni una línea de contenido.

- [ ] **Paso 1: Escribir el test que falla**

```python
# agent/tests/test_inventario.py
from pathlib import Path
from vibi_node import inventario

def test_cuenta_extensiones_sin_revelar_nombres(tmp_path):
    carpeta = tmp_path / "Farmacologia II"
    carpeta.mkdir()
    (carpeta / "tema-1-secreto.pdf").write_text("x")
    (carpeta / "tema-2-secreto.pdf").write_text("x")
    (carpeta / "notas.docx").write_text("x")

    mapa = inventario.mapa_de([tmp_path])
    entrada = [c for c in mapa["carpetas"] if c["ruta"].endswith("Farmacologia II")][0]
    assert entrada["extensiones"] == {"pdf": 2, "docx": 1}
    serializado = str(mapa)
    assert "secreto" not in serializado

def test_una_carpeta_vacia_no_aparece(tmp_path):
    (tmp_path / "vacia").mkdir()
    mapa = inventario.mapa_de([tmp_path])
    assert all(not c["ruta"].endswith("vacia") for c in mapa["carpetas"])

def test_respeta_el_tope_de_carpetas(tmp_path):
    for i in range(40):
        carpeta = tmp_path / f"c{i}"
        carpeta.mkdir()
        (carpeta / "a.pdf").write_text("x")
    mapa = inventario.mapa_de([tmp_path], tope_carpetas=25)
    assert len(mapa["carpetas"]) == 25

def test_una_raiz_que_no_existe_no_revienta(tmp_path):
    mapa = inventario.mapa_de([tmp_path / "no-existe"])
    assert mapa["carpetas"] == []
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest agent/tests/test_inventario.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'vibi_node.inventario'`

- [ ] **Paso 3: Implementación mínima**

```python
# agent/vibi_node/inventario.py
"""Un retrato del equipo que quepa en un párrafo.

La entrevista no debería preguntar lo que puede mirar: el catálogo de
aplicaciones dice poco —todo el mundo tiene un navegador— pero una carpeta
llamada `Farmacología II` con cuarenta PDF recientes dice el grado, el curso y
cómo estudia esa persona.

**Y lo que viaja es el agregado, no el contenido.** Aquí se cuentan carpetas y
extensiones y se manda eso: unos cientos de tokens. Ni un nombre de archivo ni
una línea de texto salen del equipo en este nivel. Abrir algo es el nivel 3 de
la escalada y exige permiso pedido en el momento.
"""
from __future__ import annotations

import time
from pathlib import Path

# Cuántas carpetas se describen como mucho. Las que más archivos tienen son
# las que más dicen, y a partir de unas cuantas el retrato ya no mejora.
TOPE_CARPETAS = 25

# Y cuánto se baja. Dos niveles alcanzan `Documentos/Carrera/Farmacología`,
# que es donde vive la señal; más abajo empieza a costar y a repetir.
PROFUNDIDAD = 2


def _dias_desde(momento: float) -> int:
    return max(0, int((time.time() - momento) / 86_400))


def _describir(carpeta: Path) -> dict | None:
    extensiones: dict[str, int] = {}
    ultima = 0.0
    try:
        for hijo in carpeta.iterdir():
            if not hijo.is_file():
                continue
            sufijo = hijo.suffix.lower().lstrip(".")
            if not sufijo:
                continue
            extensiones[sufijo] = extensiones.get(sufijo, 0) + 1
            try:
                ultima = max(ultima, hijo.stat().st_mtime)
            except OSError:
                continue
    except (OSError, PermissionError):
        return None
    if not extensiones:
        return None
    return {
        "ruta": str(carpeta),
        "extensiones": dict(sorted(extensiones.items(), key=lambda p: -p[1])),
        "tocada_hace_dias": _dias_desde(ultima) if ultima else None,
    }


def _bajar(raiz: Path, profundidad: int) -> list[Path]:
    if profundidad <= 0:
        return []
    encontradas: list[Path] = []
    try:
        for hijo in raiz.iterdir():
            if hijo.is_dir() and not hijo.name.startswith("."):
                encontradas.append(hijo)
                encontradas.extend(_bajar(hijo, profundidad - 1))
    except (OSError, PermissionError):
        return encontradas
    return encontradas


def mapa_de(raices: list[Path], tope_carpetas: int = TOPE_CARPETAS) -> dict:
    """Qué hay en estas carpetas, contado y sin nombres propios."""
    candidatas: list[Path] = []
    for raiz in raices:
        if not raiz.exists():
            continue
        candidatas.append(raiz)
        candidatas.extend(_bajar(raiz, PROFUNDIDAD))

    descritas = [d for d in (_describir(c) for c in candidatas) if d]
    descritas.sort(key=lambda d: -sum(d["extensiones"].values()))
    return {"carpetas": descritas[:tope_carpetas]}
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest agent/tests/test_inventario.py -v`
Esperado: PASS, los cuatro tests.

- [ ] **Paso 5: Commit**

```bash
git add agent/vibi_node/inventario.py agent/tests/test_inventario.py
git commit -m "feat(nodo): mapa agregado del disco para la entrevista"
```

---

### Tarea 8: Hipótesis a partir del inventario

**Archivos:**
- Crear: `app/perfil_entrevista.py`
- Test: `tests/test_perfil_entrevista.py`

**Interfaces:**
- Consume: el diccionario de `inventario.mapa_de()` (Tarea 7)
- Produce: `Hipotesis` (dataclass: `clase`, `valor`, `evidencia`), `hipotesis_de(mapa: dict) -> list[Hipotesis]`, `PISTAS: dict[str, tuple[str, ...]]`

**Nota sobre el alcance:** esta tarea cubre solo la parte determinista, con pistas declaradas. La expansión abierta la hace el modelo en la Tarea 9. Se separan porque esta se puede testear sin modelo y la otra no.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_perfil_entrevista.py
from app import perfil_entrevista as entrevista

MAPA_MEDICINA = {"carpetas": [
    {"ruta": r"C:\Users\x\Documentos\Farmacologia II",
     "extensiones": {"pdf": 41, "docx": 3}, "tocada_hace_dias": 2},
    {"ruta": r"C:\Users\x\Documentos\Bioquimica",
     "extensiones": {"pdf": 28, "png": 12}, "tocada_hace_dias": 21},
]}

MAPA_CODIGO = {"carpetas": [
    {"ruta": r"C:\Users\x\repos\vibi",
     "extensiones": {"py": 120, "md": 14}, "tocada_hace_dias": 0},
]}

def test_saca_el_dominio_de_los_nombres_de_carpeta():
    valores = [h.valor for h in entrevista.hipotesis_de(MAPA_MEDICINA)]
    assert "medicina" in valores

def test_saca_como_trabaja_de_las_extensiones():
    hipotesis = entrevista.hipotesis_de(MAPA_MEDICINA)
    herramientas = [h.valor for h in hipotesis if h.clase == "herramienta"]
    assert "pdf" in herramientas

def test_distingue_dominios_distintos():
    valores = [h.valor for h in entrevista.hipotesis_de(MAPA_CODIGO)]
    assert "programacion" in valores
    assert "medicina" not in valores

def test_cada_hipotesis_dice_en_que_se_apoya():
    hipotesis = entrevista.hipotesis_de(MAPA_MEDICINA)
    dominio = [h for h in hipotesis if h.valor == "medicina"][0]
    assert "Farmacologia" in dominio.evidencia or "Bioquimica" in dominio.evidencia

def test_un_mapa_vacio_no_inventa_nada():
    assert entrevista.hipotesis_de({"carpetas": []}) == []
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_perfil_entrevista.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'app.perfil_entrevista'`

- [ ] **Paso 3: Implementación mínima**

```python
# app/perfil_entrevista.py
"""Llegar a la entrevista con los deberes hechos.

Preguntar «¿a qué te dedicas?» a alguien cuyo disco ya lo dice es hacerle
perder el tiempo y quedarse con una respuesta peor: la gente resume mal lo que
hace. Aquí se sacan hipótesis del mapa del equipo, y la entrevista pasa de
cuestionario a confirmación —«veo carpetas de Farmacología con muchos PDF
recientes, ¿estudias medicina?»—.

**Una hipótesis nunca es una conclusión.** De una carpeta llamada `Bioquímica`
a «estudia medicina» hay un salto: podría ser docente, o de su pareja. Por eso
entran al perfil con procedencia `inventario` y confianza 0,4, y por eso se
confirman antes de valer nada.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Palabras que aparecen en nombres de carpeta y delatan un dominio. Es la
# parte determinista y corta a propósito: lo abierto lo hace el modelo con el
# mapa delante, y aquí solo está lo que se puede probar sin él.
PISTAS: dict[str, tuple[str, ...]] = {
    "medicina": ("farmacolog", "bioquimic", "anatomia", "fisiolog", "patolog", "histolog"),
    "programacion": ("repos", "proyectos", "src", "github", "workspace"),
    "derecho": ("civil", "penal", "mercantil", "procesal"),
    "audiovisual": ("premiere", "render", "footage", "proyecto de video"),
}

# Extensiones que dicen cómo trabaja alguien, no en qué. Un disco lleno de PDF
# es alguien que lee documentos largos, sea de la carrera que sea.
PISTAS_EXTENSION = {"pdf": "pdf", "docx": "documentos", "py": "codigo", "ipynb": "codigo"}

# Cuántos archivos de una extensión hacen que cuente. Tres PDF sueltos los
# tiene cualquiera; cuarenta son una forma de trabajar.
MINIMO_PARA_CONTAR = 10


@dataclass(frozen=True)
class Hipotesis:
    clase: str
    valor: str
    evidencia: str


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    return sin_tildes.encode("ascii", "ignore").decode("ascii").casefold()


def hipotesis_de(mapa: dict) -> list[Hipotesis]:
    """Qué se puede suponer de este equipo, y apoyándose en qué."""
    carpetas = (mapa or {}).get("carpetas") or []

    apoyos: dict[str, list[str]] = {}
    for carpeta in carpetas:
        nombre = _plano(str(carpeta.get("ruta", "")))
        for dominio, pistas in PISTAS.items():
            if any(pista in nombre for pista in pistas):
                apoyos.setdefault(dominio, []).append(
                    str(carpeta["ruta"]).rsplit("\\", 1)[-1]
                )

    conteo: dict[str, int] = {}
    for carpeta in carpetas:
        for extension, cuantos in (carpeta.get("extensiones") or {}).items():
            if extension in PISTAS_EXTENSION:
                conteo[extension] = conteo.get(extension, 0) + cuantos

    hipotesis = [
        Hipotesis("dominio", dominio, f"carpetas: {', '.join(carpetas_vistas[:3])}")
        for dominio, carpetas_vistas in sorted(apoyos.items())
    ]
    hipotesis += [
        Hipotesis("herramienta", extension, f"{cuantos} archivos .{extension}")
        for extension, cuantos in sorted(conteo.items())
        if cuantos >= MINIMO_PARA_CONTAR
    ]
    return hipotesis
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_perfil_entrevista.py -v`
Esperado: PASS, los cinco tests.

- [ ] **Paso 5: Commit**

```bash
git add app/perfil_entrevista.py tests/test_perfil_entrevista.py
git commit -m "feat(entrevista): hipotesis deterministas desde el mapa del equipo"
```

---

### Tarea 9: La propuesta en dos bloques

**Archivos:**
- Modificar: `app/perfil_entrevista.py`
- Test: `tests/test_perfil_entrevista.py`

**Interfaces:**
- Consume: `registro_mcp.buscar()`, `registro_mcp.verificar()` (Tareas 5 y 6), `Hipotesis` (Tarea 8)
- Produce: `Propuesta` (dataclass: `tipo`, `referencia`, `titulo`, `justificacion`, `transporte`, `bloque`), `proponer(terminos_pedidos, terminos_adyacentes, buscador=None, verificador=None) -> list[Propuesta]`

**Los dos bloques:** `bloque="pedido"` para lo que deriva de algo que el usuario dijo; `bloque="encaja"` para lo que sale de la expansión por adyacencia. El usuario tiene que poder distinguirlos.

- [ ] **Paso 1: Escribir el test que falla**

```python
from app import registro_mcp

def _servidor(nombre, transporte="remoto"):
    return registro_mcp.Servidor(nombre, nombre.upper(), "desc", "1.0", "https://x", transporte, True)

def test_separa_lo_pedido_de_lo_que_encaja():
    def buscador(termino, limite=10):
        return {"pdf": [_servidor("a/pdf")], "citas": [_servidor("b/citas")]}.get(termino, [])

    propuestas = entrevista.proponer(
        terminos_pedidos=["pdf"], terminos_adyacentes=["citas"],
        buscador=buscador, verificador=lambda s: (True, ""),
    )
    por_ref = {p.referencia: p.bloque for p in propuestas}
    assert por_ref["a/pdf"] == "pedido"
    assert por_ref["b/citas"] == "encaja"

def test_lo_que_no_verifica_no_se_propone():
    def buscador(termino, limite=10):
        return [_servidor("a/roto")]
    propuestas = entrevista.proponer(
        terminos_pedidos=["pdf"], terminos_adyacentes=[],
        buscador=buscador, verificador=lambda s: (False, "no responde"),
    )
    assert propuestas == []

def test_no_se_repite_un_servidor_en_los_dos_bloques():
    def buscador(termino, limite=10):
        return [_servidor("a/pdf")]
    propuestas = entrevista.proponer(
        terminos_pedidos=["pdf"], terminos_adyacentes=["lectura"],
        buscador=buscador, verificador=lambda s: (True, ""),
    )
    assert len(propuestas) == 1
    assert propuestas[0].bloque == "pedido"

def test_la_propuesta_lleva_el_transporte_para_que_se_vea_el_riesgo():
    def buscador(termino, limite=10):
        return [_servidor("a/local", transporte="local")]
    propuestas = entrevista.proponer(
        terminos_pedidos=["x"], terminos_adyacentes=[],
        buscador=buscador, verificador=lambda s: (True, ""),
    )
    assert propuestas[0].transporte == "local"
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_perfil_entrevista.py -v -k propone or bloque`
Esperado: FAIL con `AttributeError: module 'app.perfil_entrevista' has no attribute 'proponer'`

- [ ] **Paso 3: Implementación mínima**

Añade a `app/perfil_entrevista.py`:

```python
from . import registro_mcp


@dataclass(frozen=True)
class Propuesta:
    tipo: str
    referencia: str
    titulo: str
    justificacion: str
    transporte: str
    bloque: str


def proponer(
    terminos_pedidos: list[str],
    terminos_adyacentes: list[str],
    buscador=None,
    verificador=None,
) -> list[Propuesta]:
    """Lo que se le enseña al usuario para que apruebe, en dos montones.

    **Separar los dos bloques no es cosmético.** «Esto te lo pongo porque me lo
    has pedido» y «esto además lo he encontrado yo» merecen niveles de
    confianza distintos por parte de quien lee, y mezclarlos hace que la
    expansión contamine lo pedido.

    Nada llega aquí sin verificarse: proponer lo no comprobado empeora el
    sistema, porque el usuario aprueba dando por hecho que se miró.
    """
    buscar = buscador or registro_mcp.buscar
    verificar = verificador or registro_mcp.verificar

    propuestas: list[Propuesta] = []
    ya_vistos: set[str] = set()

    for bloque, terminos in (("pedido", terminos_pedidos), ("encaja", terminos_adyacentes)):
        for termino in terminos:
            for servidor in buscar(termino):
                if servidor.nombre in ya_vistos:
                    continue
                vale, _motivo = verificar(servidor)
                if not vale:
                    continue
                ya_vistos.add(servidor.nombre)
                propuestas.append(
                    Propuesta(
                        tipo="mcp",
                        referencia=servidor.nombre,
                        titulo=servidor.titulo,
                        justificacion=servidor.descripcion,
                        transporte=servidor.transporte,
                        bloque=bloque,
                    )
                )
    return propuestas
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_perfil_entrevista.py -v`
Esperado: PASS, los nueve tests.

- [ ] **Paso 5: Commit**

```bash
git add app/perfil_entrevista.py tests/test_perfil_entrevista.py
git commit -m "feat(entrevista): propuesta verificada en dos bloques"
```

---

## Fase 5 — Enganchar con el sistema vivo

### Tarea 10: Los MCP aprobados llegan al motor

**Archivos:**
- Modificar: `app/executors/agy_mcp_config.py` (función `servidores_externos`)
- Test: `tests/test_agy_mcp_config_perfil.py`

**Interfaces:**
- Consume: `perfil.capacidades_de()` (Tarea 3), `perfil_activador.decidir()` (Tarea 4)
- Produce: ningún símbolo nuevo; cambia el comportamiento de `construir_servidores(user_id, ...)`

**Cuidado:** un valor `None` en el diccionario significa «borra esta entrada», no «déjala como está». Un MCP que baja a `catalogo` tiene que salir con `None`, no ausente, o se queda declarado para siempre.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_agy_mcp_config_perfil.py
from app import perfil
from app.executors import agy_mcp_config

def test_un_mcp_aprobado_en_completo_se_declara():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("u1", "mcp", "ai.pdfassistant/pdfassistant",
                             "Lee tus PDF", transporte="remoto")
    declarados = agy_mcp_config.del_perfil("u1")
    assert "ai.pdfassistant/pdfassistant" in declarados
    assert declarados["ai.pdfassistant/pdfassistant"] is not None

def test_un_mcp_bajado_a_catalogo_se_borra_explicitamente():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("u2", "mcp", "b/dos", "algo", transporte="remoto")
    perfil.fijar_nivel("u2", "mcp", "b/dos", "catalogo")
    declarados = agy_mcp_config.del_perfil("u2")
    assert declarados["b/dos"] is None

def test_sin_perfil_no_se_declara_nada():
    perfil.crear_tablas()
    assert agy_mcp_config.del_perfil("usuario-sin-perfil") == {}
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_agy_mcp_config_perfil.py -v`
Esperado: FAIL con `AttributeError: module has no attribute 'del_perfil'`

- [ ] **Paso 3: Implementación mínima**

Añade a `app/executors/agy_mcp_config.py`:

```python
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
        cap["referencia"]: ({"transporte": cap["transporte"]} if cap["referencia"] in activos else None)
        for cap in capacidades
    }
```

Y en `construir_servidores()`, justo antes del `return`, fusiona el resultado:

```python
    servidores.update(del_perfil(user_id))
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_agy_mcp_config_perfil.py tests/test_agy_mcp.py -v`
Esperado: PASS. Los tests existentes de `agy_mcp` deben seguir en verde: si alguno se rompe, es que `del_perfil` está pisando un servidor gestionado y hay que revisar el orden del `update`.

- [ ] **Paso 5: Commit**

```bash
git add app/executors/agy_mcp_config.py tests/test_agy_mcp_config_perfil.py
git commit -m "feat(perfil): los MCP del perfil llegan al motor"
```

---

### Tarea 11: El resumen del perfil entra en GEMINI.md

**Archivos:**
- Modificar: `app/executors/antigravity_chat.py` (donde se escribe `ARCHIVO_REGLAS`, sobre la línea 1683)
- Test: `tests/test_antigravity_perfil.py`

**Interfaces:**
- Consume: `perfil_activador.Configuracion.resumen` (Tarea 4)
- Produce: `bloque_de_perfil(resumen: str) -> str`, `fusionar_reglas(texto_actual: str, resumen: str) -> str`, constantes `MARCA_INICIO`, `MARCA_FIN`

**Por qué entre marcas:** en ese archivo vive la personalidad y las reglas de locución, y moverlas de sitio fue lo que bajó la primera respuesta de voz de 32-56 s a 1,3-2,1 s. El perfil se añade sin tocar nada de eso.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_antigravity_perfil.py
from app.executors import antigravity_chat as motor

def test_el_bloque_se_inserta_al_final_si_no_estaba():
    resultado = motor.fusionar_reglas("Eres Vibi.\n", "Se dedica a: medicina.")
    assert "Eres Vibi." in resultado
    assert "medicina" in resultado
    assert motor.MARCA_INICIO in resultado

def test_reescribir_no_duplica_el_bloque():
    una = motor.fusionar_reglas("Eres Vibi.\n", "Se dedica a: medicina.")
    dos = motor.fusionar_reglas(una, "Se dedica a: derecho.")
    assert dos.count(motor.MARCA_INICIO) == 1
    assert "derecho" in dos
    assert "medicina" not in dos

def test_no_se_toca_nada_fuera_de_las_marcas():
    original = "Eres Vibi.\nHabla en espanol.\n"
    resultado = motor.fusionar_reglas(original, "Se dedica a: medicina.")
    assert resultado.startswith(original)

def test_un_resumen_vacio_borra_el_bloque():
    con = motor.fusionar_reglas("Eres Vibi.\n", "Se dedica a: medicina.")
    sin = motor.fusionar_reglas(con, "")
    assert motor.MARCA_INICIO not in sin
    assert sin.startswith("Eres Vibi.")
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_antigravity_perfil.py -v`
Esperado: FAIL con `AttributeError: module has no attribute 'fusionar_reglas'`

- [ ] **Paso 3: Implementación mínima**

Añade a `app/executors/antigravity_chat.py`:

```python
# El bloque del perfil vive delimitado porque en este archivo también está la
# personalidad y las reglas de locución, y ahí es donde tienen que estar: fue
# sacarlas del turno lo que bajó la primera respuesta de voz de 32-56 s a
# 1,3-2,1 s. Escribir el perfil sin marcas obligaría a reescribir el archivo
# entero y se llevaría eso por delante.
MARCA_INICIO = "<!-- perfil:inicio -->"
MARCA_FIN = "<!-- perfil:fin -->"


def bloque_de_perfil(resumen: str) -> str:
    return f"{MARCA_INICIO}\n## Quién tienes delante\n\n{resumen.strip()}\n{MARCA_FIN}"


def fusionar_reglas(texto_actual: str, resumen: str) -> str:
    """Pone el perfil al día sin tocar una línea de lo demás."""
    texto = texto_actual or ""
    inicio = texto.find(MARCA_INICIO)
    if inicio != -1:
        fin = texto.find(MARCA_FIN, inicio)
        if fin != -1:
            texto = texto[:inicio] + texto[fin + len(MARCA_FIN):]
        texto = texto.rstrip() + "\n"

    if not (resumen or "").strip():
        return texto
    return texto.rstrip() + "\n\n" + bloque_de_perfil(resumen) + "\n"
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_antigravity_perfil.py tests/test_antigravity_chat.py -v`
Esperado: PASS, incluidos los tests existentes del motor.

- [ ] **Paso 5: Commit**

```bash
git add app/executors/antigravity_chat.py tests/test_antigravity_perfil.py
git commit -m "feat(perfil): el resumen del perfil entra en GEMINI.md entre marcas"
```

---

## Fase 6 — El observador

### Tarea 12: Las señales del uso

**Archivos:**
- Crear: `app/perfil_observador.py`
- Test: `tests/test_perfil_observador.py`

**Interfaces:**
- Consume: tablas `tool_invocations`, `recetas`, `perfil_capacidades`
- Produce: `Senales` (dataclass: `herramientas_usadas: dict[str, int]`, `apps_con_receta: tuple[str, ...]`, `capacidades_sin_usar: tuple[tuple[str, str], ...]`), `leer_senales(user_id, desde: float) -> Senales`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_perfil_observador.py
import time
from app import db, perfil, perfil_observador as observador

def test_las_capacidades_nunca_usadas_salen_listadas():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("o1", "mcp", "a/uno", "x")
    perfil.aprobar_capacidad("o1", "mcp", "b/dos", "x")
    perfil.registrar_uso_capacidad("o1", "mcp", "a/uno")
    senales = observador.leer_senales("o1", desde=0)
    assert ("mcp", "b/dos") in senales.capacidades_sin_usar
    assert ("mcp", "a/uno") not in senales.capacidades_sin_usar

def test_las_recetas_cuentan_como_apps_que_se_manejan():
    perfil.crear_tablas()
    from app import recetas
    recetas.crear_tablas()
    recetas.guardar("whatsapp", "cdp", "mapa de la interfaz", comprobacion="abrí un chat")
    senales = observador.leer_senales("o2", desde=0)
    assert "whatsapp" in senales.apps_con_receta

def test_sin_nada_que_leer_las_senales_vienen_vacias():
    perfil.crear_tablas()
    senales = observador.leer_senales("o3", desde=time.time() + 1000)
    assert senales.herramientas_usadas == {}
    assert senales.capacidades_sin_usar == ()
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_perfil_observador.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'app.perfil_observador'`

- [ ] **Paso 3: Implementación mínima**

```python
# app/perfil_observador.py
"""Mirar lo que el usuario hace de verdad, y ajustar lo que se creía.

**Aquí no piensa nadie: se cuenta.** Es el mismo reparto que en `avisos.py` y
`vigilancias.py`, y por el mismo motivo: la parte tonta sale gratis y puede
correr siempre, y el modelo entra una vez por revisión —cuatro llamadas al
mes— en vez de una vez por evento. Un heartbeat de cinco minutos costaría 288
llamadas diarias haya pasado algo o no.

**Y no lee el disco.** Mirar los archivos del usuario pertenece a la
entrevista, con su escalada y su permiso. Aquí solo se leen contadores que ya
están en la base: ningún dato nuevo sale hacia el modelo.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import db


@dataclass(frozen=True)
class Senales:
    herramientas_usadas: dict[str, int]
    apps_con_receta: tuple[str, ...]
    capacidades_sin_usar: tuple[tuple[str, str], ...]


def leer_senales(user_id: str, desde: float) -> Senales:
    """Todo lo observable desde ese momento, en una sola pasada."""
    with db._conn() as c:
        usadas: dict[str, int] = {}
        try:
            for fila in c.execute(
                """SELECT tool_id, COUNT(*) AS veces FROM tool_invocations
                   WHERE created_at >= ? GROUP BY tool_id""",
                (desde,),
            ):
                usadas[str(fila["tool_id"])] = int(fila["veces"])
        except Exception:  # noqa: BLE001 - la tabla puede no existir aún
            usadas = {}

        apps: tuple[str, ...] = ()
        try:
            apps = tuple(
                str(f["app"])
                for f in c.execute("SELECT app FROM recetas ORDER BY app")
            )
        except Exception:  # noqa: BLE001
            apps = ()

        sin_usar = tuple(
            (str(f["tipo"]), str(f["referencia"]))
            for f in c.execute(
                """SELECT tipo, referencia FROM perfil_capacidades
                   WHERE user_id=? AND usos = 0""",
                (user_id,),
            )
        )

    return Senales(
        herramientas_usadas=usadas,
        apps_con_receta=apps,
        capacidades_sin_usar=sin_usar,
    )
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_perfil_observador.py -v`
Esperado: PASS, los tres tests.

- [ ] **Paso 5: Commit**

```bash
git add app/perfil_observador.py tests/test_perfil_observador.py
git commit -m "feat(observador): leer las senales de uso que ya existen"
```

---

### Tarea 13: La revisión que mueve el perfil

**Archivos:**
- Modificar: `app/perfil_observador.py`
- Test: `tests/test_perfil_observador.py`

**Interfaces:**
- Consume: `Senales` (Tarea 12), `perfil.apoyar/contradecir/decaer/fijar_nivel/nivel_para` (Tareas 2 y 3)
- Produce: `revisar(user_id, senales) -> dict` con `{"apoyadas": [...], "decaidas": [...], "propuestas_retirada": [...]}`

- [ ] **Paso 1: Escribir el test que falla**

```python
def test_una_capacidad_sin_usar_baja_de_nivel():
    perfil.crear_tablas()
    perfil.afirmar("o4", "herramienta", "pdf", "entrevista")
    perfil.aprobar_capacidad("o4", "mcp", "a/pdf", "Lee PDF")
    senales = observador.Senales({}, (), (("mcp", "a/pdf"),))
    # Cuatro revisiones sin uso: 0,6 → 0,4 → nivel catalogo
    for _ in range(4):
        observador.revisar("o4", senales)
    cap = [c for c in perfil.capacidades_de("o4") if c["referencia"] == "a/pdf"][0]
    assert cap["nivel"] == "catalogo"

def test_una_app_con_receta_apoya_su_afirmacion():
    perfil.crear_tablas()
    perfil.afirmar("o5", "herramienta", "whatsapp", "inventario")
    senales = observador.Senales({}, ("whatsapp",), ())
    observador.revisar("o5", senales)
    a = [x for x in perfil.afirmaciones_de("o5") if x["valor"] == "whatsapp"][0]
    assert a["confianza"] == pytest.approx(0.5)

def test_la_revision_informa_de_lo_que_ha_movido():
    perfil.crear_tablas()
    perfil.afirmar("o6", "herramienta", "whatsapp", "inventario")
    resultado = observador.revisar("o6", observador.Senales({}, ("whatsapp",), ()))
    assert "whatsapp" in resultado["apoyadas"]
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_perfil_observador.py -v -k revisar or nivel or apoya`
Esperado: FAIL con `AttributeError: module 'app.perfil_observador' has no attribute 'revisar'`

- [ ] **Paso 3: Implementación mínima**

Añade a `app/perfil_observador.py` (y `from . import perfil` arriba):

```python
def revisar(user_id: str, senales: Senales) -> dict:
    """Mueve las confianzas y devuelve qué ha cambiado.

    Mover confianzas es aritmética y no necesita modelo. El modelo entra
    después y solo para redactar la propuesta que se le enseña al usuario.

    Cuando lo observado contradice lo declarado en la entrevista, **gana lo
    observado**: lo que alguien hace pesa más que lo que dijo que haría.
    """
    apoyadas: list[str] = []
    for app in senales.apps_con_receta:
        for afirmacion in perfil.afirmaciones_de(user_id, "herramienta"):
            if afirmacion["valor"] in app or app in afirmacion["valor"]:
                perfil.apoyar(user_id, "herramienta", afirmacion["valor"])
                apoyadas.append(afirmacion["valor"])

    decaidas: list[str] = []
    propuestas: list[str] = []
    for tipo, referencia in senales.capacidades_sin_usar:
        capacidad = [
            c for c in perfil.capacidades_de(user_id, tipo)
            if c["referencia"] == referencia
        ]
        if not capacidad:
            continue
        relacionadas = [
            (a["clase"], a["valor"])
            for a in perfil.afirmaciones_de(user_id)
            if a["valor"] in capacidad[0]["justificacion"].casefold()
        ]
        perfil.decaer(user_id, sin_uso=relacionadas or [("herramienta", referencia)])
        decaidas.append(referencia)

        confianzas = [
            a["confianza"]
            for a in perfil.afirmaciones_de(user_id)
            if (a["clase"], a["valor"]) in relacionadas
        ]
        # Sin afirmación que la sostenga, una capacidad que nadie usa no tiene
        # a qué agarrarse: se trata como confianza nula.
        nivel = perfil.nivel_para(min(confianzas) if confianzas else 0.0)
        perfil.fijar_nivel(user_id, tipo, referencia, nivel)
        if nivel == "propuesta_retirada":
            propuestas.append(referencia)

    return {
        "apoyadas": apoyadas,
        "decaidas": decaidas,
        "propuestas_retirada": propuestas,
    }
```

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_perfil_observador.py -v`
Esperado: PASS, los seis tests.

- [ ] **Paso 5: Commit**

```bash
git add app/perfil_observador.py tests/test_perfil_observador.py
git commit -m "feat(observador): revision que mueve confianzas y niveles"
```

---

## Fase 7 — El instrumental de la evaluación

### Tarea 14: Medir lo que el TFG tiene que demostrar

**Archivos:**
- Crear: `app/perfil_metricas.py`
- Test: `tests/test_perfil_metricas.py`

**Interfaces:**
- Consume: `perfil.capacidades_de()` (Tarea 3)
- Produce: `tasa_de_aceptacion(propuestas, aprobadas) -> float`, `supervivencia(user_id, dias: int, ahora: float | None = None) -> float`

**Por qué está en el plan y no fuera:** la contribución del trabajo es la evaluación, y una métrica que se calcula a mano el día antes de la defensa no es una métrica. La supervivencia a los N días es la que ningún trabajo del área reporta.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_perfil_metricas.py
import time
import pytest
from app import perfil, perfil_metricas as metricas

DIA = 86_400

def test_tasa_de_aceptacion():
    assert metricas.tasa_de_aceptacion(propuestas=10, aprobadas=4) == pytest.approx(0.4)
    assert metricas.tasa_de_aceptacion(propuestas=0, aprobadas=0) == 0.0

def test_supervivencia_cuenta_las_usadas_despues_del_plazo():
    perfil.crear_tablas()
    ahora = time.time()
    perfil.aprobar_capacidad("m1", "mcp", "viva/uno", "x")
    perfil.aprobar_capacidad("m1", "mcp", "muerta/dos", "x")
    perfil.registrar_uso_capacidad("m1", "mcp", "viva/uno")
    assert metricas.supervivencia("m1", dias=14, ahora=ahora) == pytest.approx(0.5)

def test_solo_cuentan_las_aprobadas_hace_mas_del_plazo():
    perfil.crear_tablas()
    perfil.aprobar_capacidad("m2", "mcp", "recien/uno", "x")
    # Aprobada hoy: todavía no ha tenido dos semanas para demostrar nada.
    assert metricas.supervivencia("m2", dias=14) == 0.0

def test_sin_capacidades_la_supervivencia_es_cero_y_no_revienta():
    perfil.crear_tablas()
    assert metricas.supervivencia("m3", dias=14) == 0.0
```

- [ ] **Paso 2: Ejecutar y ver que falla**

Ejecuta: `python -m pytest tests/test_perfil_metricas.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'app.perfil_metricas'`

- [ ] **Paso 3: Implementación mínima**

```python
# app/perfil_metricas.py
"""Los números con los que se defiende que esto sirve para algo.

Dos métricas, y la segunda es la que no reporta nadie del área. Skilldex puntúa
si el `SKILL.md` tiene el frontmatter bien puesto y sus propios autores aclaran
que eso «explicitly is not a measure of functional quality». Medir si la
capacidad instalada **seguía usándose dos semanas después** sí lo es.
"""
from __future__ import annotations

import time

from . import perfil

DIA = 86_400


def tasa_de_aceptacion(propuestas: int, aprobadas: int) -> float:
    """Qué proporción de lo propuesto le pareció bien al usuario."""
    if propuestas <= 0:
        return 0.0
    return aprobadas / propuestas


def supervivencia(user_id: str, dias: int, ahora: float | None = None) -> float:
    """De lo aprobado hace más de `dias`, cuánto se sigue usando.

    Las aprobadas hace menos del plazo **no cuentan en el denominador**: no han
    tenido tiempo de demostrar nada, y meterlas hundiría la métrica por una
    razón que no tiene que ver con acertar.
    """
    momento = ahora if ahora is not None else time.time()
    limite = momento - dias * DIA
    maduras = [
        c for c in perfil.capacidades_de(user_id)
        if c["aprobada_en"] is not None and c["aprobada_en"] <= limite
    ]
    if not maduras:
        return 0.0
    vivas = [c for c in maduras if (c["usos"] or 0) > 0]
    return len(vivas) / len(maduras)
```

**Nota para el implementador:** el segundo test aprueba la capacidad «ahora», así que para que `supervivencia` la considere madura hay que llamarla con un `ahora` desplazado. Si el test falla porque `aprobada_en` es demasiado reciente, es el comportamiento correcto — ajusta el test pasando `ahora=time.time() + 15 * DIA`, no el código.

- [ ] **Paso 4: Ejecutar y ver que pasa**

Ejecuta: `python -m pytest tests/test_perfil_metricas.py -v`
Esperado: PASS, los cuatro tests.

- [ ] **Paso 5: Commit**

```bash
git add app/perfil_metricas.py tests/test_perfil_metricas.py
git commit -m "feat(metricas): tasa de aceptacion y supervivencia de capacidades"
```

---

## Autorrevisión del plan

**Cobertura de la spec:**

| Sección de la spec | Tarea |
|---|---|
| Modelo de datos (3 tablas) | 1, 3 |
| Movimiento de confianza y umbrales | 2 |
| Nivel intermedio por tipo | 3, 4, 10 |
| El activador puro | 4 |
| Registro de MCP y verificación | 5, 6 |
| Escalada de evidencia, nivel 1 | 7 |
| Hipótesis desde el inventario | 8 |
| Búsqueda en dos niveles y propuesta | 9 |
| Activación: MCP | 10 |
| Activación: `GEMINI.md` | 11 |
| El observador | 12, 13 |
| Evaluación | 14 |
| Nivel 3 de la escalada (contenido) | **Tarea 0 primero** |

**Huecos conocidos y por qué se quedan fuera de este plan:**

- **La API HTTP y la interfaz de la entrevista.** Este plan deja el motor completo y probado; los endpoints y la pantalla son un plan aparte, porque hasta que la lógica no esté cerrada la forma de la API cambiaría dos veces.
- **La activación de skills y vigilancias.** El activador ya las decide (Tarea 4), pero engancharlas exige que la entrevista pueda crearlas, y eso viene con la API.
- **El nivel 2 y 3 de la escalada de evidencia.** Dependen del resultado de la Tarea 0.

Los tres son continuación natural, no olvidos, y cada uno merece su propio plan cuando llegue.

---

## Ejecución

Al terminar cada tarea, ejecuta **solo los tests del área tocada**, nunca la suite entera: los tests del nodo abren aplicaciones en la pantalla.
