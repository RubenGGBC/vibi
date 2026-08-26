import asyncio
from types import SimpleNamespace

from app import perfil_entrevista as entrevista

MAPA_MEDICINA = {"carpetas": [
    {"ruta": r"Documentos\Farmacologia II",
     "extensiones": {"pdf": 41, "docx": 3}, "tocada_hace_dias": 2},
    {"ruta": r"Documentos\Bioquimica",
     "extensiones": {"pdf": 28, "png": 12}, "tocada_hace_dias": 21},
]}

MAPA_CODIGO = {"carpetas": [
    {"ruta": r"repos\vibi",
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

# ===== CORRECCIÓN 1: No disparar por subcadena suelta =====

def test_no_dispara_repos_dentro_de_reposteria():
    """'repos' dentro de 'Reposteria' no debe ser programacion."""
    mapa = {"carpetas": [
        {"ruta": r"Documentos\Recetas de Reposteria",
         "extensiones": {"docx": 5}, "tocada_hace_dias": 1},
    ]}
    dominios = [h.valor for h in entrevista.hipotesis_de(mapa) if h.clase == "dominio"]
    assert "programacion" not in dominios

def test_no_dispara_render_dentro_de_aprender():
    """'render' dentro de 'aprender' no debe ser audiovisual."""
    mapa = {"carpetas": [
        {"ruta": r"Documentos\Cosas para aprender",
         "extensiones": {"pdf": 5}, "tocada_hace_dias": 1},
    ]}
    dominios = [h.valor for h in entrevista.hipotesis_de(mapa) if h.clase == "dominio"]
    assert "audiovisual" not in dominios

def test_no_dispara_penal_dentro_de_penalti():
    """'penal' dentro de 'penalti' no debe ser derecho."""
    mapa = {"carpetas": [
        {"ruta": r"Documentos\Penaltis del Madrid",
         "extensiones": {"mp4": 50}, "tocada_hace_dias": 1},
    ]}
    dominios = [h.valor for h in entrevista.hipotesis_de(mapa) if h.clase == "dominio"]
    assert "derecho" not in dominios

def test_farmacologia_con_tilde_sigue_siendo_medicina():
    """farmacología (con tilde) debe detectarse como medicina."""
    mapa = {"carpetas": [
        {"ruta": r"Documentos\Farmacología",
         "extensiones": {"pdf": 15}, "tocada_hace_dias": 1},
    ]}
    valores = [h.valor for h in entrevista.hipotesis_de(mapa)]
    assert "medicina" in valores

def test_src_como_palabra_completa_es_programacion():
    """'src' como palabra completa debe detectarse."""
    mapa = {"carpetas": [
        {"ruta": r"Proyectos\src",
         "extensiones": {"py": 30}, "tocada_hace_dias": 1},
    ]}
    valores = [h.valor for h in entrevista.hipotesis_de(mapa)]
    assert "programacion" in valores

# ===== CORRECCIÓN 2: Agregar extensiones por su tipo =====

def test_agrupa_py_e_ipynb_como_codigo():
    """py=6 e ipynb=6 juntos suman 12 > 10, una sola hipotesis 'codigo'."""
    mapa = {"carpetas": [
        {"ruta": r"Proyectos\python",
         "extensiones": {"py": 6, "ipynb": 6}, "tocada_hace_dias": 1},
    ]}
    hipotesis = entrevista.hipotesis_de(mapa)
    herramientas = [h.valor for h in hipotesis if h.clase == "herramienta"]
    # Debe haber una sola entrada "codigo", no "py" ni "ipynb" por separado
    assert "codigo" in herramientas
    assert "py" not in herramientas
    assert "ipynb" not in herramientas

# ===== TAREA 9: Propuesta en dos bloques =====

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


# ===== CORRECCIÓN 1: Deduplicación completa (fallos incluidos) =====

def test_no_reintenta_un_servidor_que_fallo_en_pedido():
    """Un servidor que falla en 'pedido' no se re-verifica si aparece en 'encaja'."""
    llamadas = []

    def buscador(termino, limite=10):
        # El mismo servidor aparece en ambos términos
        return [_servidor("a/roto")]

    def verificador(s):
        llamadas.append(s.nombre)
        return (False, "no responde")

    propuestas = entrevista.proponer(
        terminos_pedidos=["pdf"], terminos_adyacentes=["citas"],
        buscador=buscador, verificador=verificador,
    )
    # No se propone nada
    assert propuestas == []
    # Pero se intentó verificar una sola vez (la primera vez que lo vio)
    assert llamadas == ["a/roto"]


def test_no_reintenta_servidor_en_dos_terminos_del_mismo_bloque():
    """El mismo servidor de dos términos distintos se verifica una sola vez."""
    llamadas = []

    def buscador(termino, limite=10):
        # Devuelve el mismo servidor para cualquier término
        return [_servidor("a/pdf")]

    def verificador(s):
        llamadas.append(s.nombre)
        return (True, "")

    propuestas = entrevista.proponer(
        terminos_pedidos=["pdf", "documento"],  # Dos términos, mismo servidor
        terminos_adyacentes=[],
        buscador=buscador, verificador=verificador,
    )
    # Se propone una sola vez
    assert len(propuestas) == 1
    # Y se verificó una sola vez
    assert llamadas == ["a/pdf"]


def test_descripcion_larga_se_recorta():
    """Una descripción que excede MAX_JUSTIFICACION se trunca legiblemente."""
    desc_larga = "a" * 400  # Mayor que MAX_JUSTIFICACION (300)

    def buscador(termino, limite=10):
        servidor = _servidor("a/pdf")
        # Reemplazamos la descripción con una larga
        return [registro_mcp.Servidor(
            nombre=servidor.nombre,
            titulo=servidor.titulo,
            descripcion=desc_larga,
            version=servidor.version,
            web=servidor.web,
            transporte=servidor.transporte,
            activo=servidor.activo,
        )]

    propuestas = entrevista.proponer(
        terminos_pedidos=["pdf"], terminos_adyacentes=[],
        buscador=buscador, verificador=lambda s: (True, ""),
    )
    assert len(propuestas) == 1
    # Debe estar truncada a ≤ 300
    assert len(propuestas[0].justificacion) <= 300
    # Debe tener elipsis
    assert propuestas[0].justificacion.endswith("…")


def test_descripcion_corta_no_se_toca():
    """Una descripción que está dentro del límite no se modifica."""
    desc_corta = "Una descripción normal y breve"

    def buscador(termino, limite=10):
        servidor = _servidor("a/pdf")
        return [registro_mcp.Servidor(
            nombre=servidor.nombre,
            titulo=servidor.titulo,
            descripcion=desc_corta,
            version=servidor.version,
            web=servidor.web,
            transporte=servidor.transporte,
            activo=servidor.activo,
        )]

    propuestas = entrevista.proponer(
        terminos_pedidos=["pdf"], terminos_adyacentes=[],
        buscador=buscador, verificador=lambda s: (True, ""),
    )
    assert len(propuestas) == 1
    # Debe ser exactamente igual
    assert propuestas[0].justificacion == desc_corta


# ===== Términos desde texto libre de la entrevista =====

def test_reconoce_varias_pistas_en_una_respuesta():
    terminos = entrevista.terminos_de_texto("Quiero que me ayude con mis apuntes y a leer PDF")
    assert "notes" in terminos
    assert "pdf" in terminos


def test_no_dispara_git_dentro_de_digital():
    """'git' no debe encontrarse dentro de 'digital', igual que 'repos' en 'reposteria'."""
    terminos = entrevista.terminos_de_texto("Quiero un asistente de marketing digital")
    assert "github" not in terminos


def test_no_dispara_nota_dentro_de_anotacion():
    terminos = entrevista.terminos_de_texto("Que lleve la anotacion de reuniones al dia")
    assert "notes" not in terminos


def test_reconoce_palabra_con_tilde():
    terminos = entrevista.terminos_de_texto("Estudio medicina y necesito ayuda clínica")
    assert "medicine" in terminos


def test_una_respuesta_sin_pistas_no_inventa_nada():
    assert entrevista.terminos_de_texto("Prefiero respuestas cortas y en español") == []


def test_texto_vacio_no_inventa_nada():
    assert entrevista.terminos_de_texto("") == []


def test_los_terminos_salen_sin_duplicados_y_ordenados():
    terminos = entrevista.terminos_de_texto("Nota, notas, apuntes y más apuntes de PDF y pdfs")
    assert terminos == sorted(set(terminos))
    assert terminos.count("notes") == 1


def test_el_termino_devuelto_es_para_buscar_no_la_etiqueta_de_dominio():
    """El registro MCP está en inglés: la pista puede ser en español, el
    término que se manda a `registro_mcp.buscar()` no.

    Antes esta función devolvía literalmente "derecho" o "audiovisual", que
    contra el registro real no encontraban nada (probado en vivo). Un test
    que solo comprobara que "se reconoce el dominio" sin mirar la palabra
    exacta devuelta no habría detectado esto.
    """
    assert entrevista.terminos_de_texto("Estudio derecho penal") == ["legal"]
    assert entrevista.terminos_de_texto("Hago montaje de video") == ["video"]
    assert entrevista.terminos_de_texto("Programo en Python") == ["programming"]
    assert entrevista.terminos_de_texto("Necesito organizar mi agenda") == ["calendar"]
    assert entrevista.terminos_de_texto("Uso mucho el correo y gmail") == ["email"]


# ===== Términos vía IA (Groq), con el diccionario como respaldo =====


class _ClienteGroqFalso:
    """Doble de AsyncGroq: mismo camino `.chat.completions.create(...)`."""

    def __init__(self, contenido: str | None = None, excepcion: Exception | None = None):
        self._contenido = contenido
        self._excepcion = excepcion
        self.llamadas = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._crear))

    async def _crear(self, **kwargs):
        self.llamadas += 1
        if self._excepcion:
            raise self._excepcion
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._contenido))]
        )


def test_ia_devuelve_los_terminos_del_json():
    cliente = _ClienteGroqFalso(contenido='{"terminos": ["oceanography", "marine data"]}')
    terminos = asyncio.run(entrevista.terminos_de_texto_ia("Estudio oceanografia", cliente=cliente))
    assert terminos == ["oceanography", "marine data"]


def test_ia_recorta_a_cinco_y_limpia_caracteres_raros():
    contenido = '{"terminos": ["A!", "b", "c", "d", "e", "f<script>"]}'
    cliente = _ClienteGroqFalso(contenido=contenido)
    terminos = asyncio.run(entrevista.terminos_de_texto_ia("x", cliente=cliente))
    assert terminos == ["a", "b", "c", "d", "e"]


def test_ia_cae_al_diccionario_si_el_cliente_falla():
    """Groq caído no debe colgar la entrevista: se cae al diccionario."""
    cliente = _ClienteGroqFalso(excepcion=RuntimeError("timeout"))
    terminos = asyncio.run(entrevista.terminos_de_texto_ia("Estudio derecho penal", cliente=cliente))
    assert terminos == ["legal"]


def test_ia_cae_al_diccionario_si_el_json_es_invalido():
    cliente = _ClienteGroqFalso(contenido="esto no es json")
    terminos = asyncio.run(entrevista.terminos_de_texto_ia("Estudio derecho penal", cliente=cliente))
    assert terminos == ["legal"]


def test_ia_cae_al_diccionario_si_terminos_no_es_una_lista():
    cliente = _ClienteGroqFalso(contenido='{"terminos": "legal"}')
    terminos = asyncio.run(entrevista.terminos_de_texto_ia("Estudio derecho penal", cliente=cliente))
    assert terminos == ["legal"]


def test_ia_texto_vacio_no_llama_al_cliente():
    cliente = _ClienteGroqFalso(contenido='{"terminos": ["x"]}')
    terminos = asyncio.run(entrevista.terminos_de_texto_ia("   ", cliente=cliente))
    assert terminos == []
    assert cliente.llamadas == 0
