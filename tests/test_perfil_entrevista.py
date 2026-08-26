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
