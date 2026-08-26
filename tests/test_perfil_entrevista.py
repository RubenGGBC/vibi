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
