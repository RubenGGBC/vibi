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
