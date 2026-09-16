from app.equipo_iniciativa import Candidata, elegir


def test_elige_las_mejores_dentro_del_presupuesto():
    candidatas = [
        Candidata(1, 10, 1.0),
        Candidata(2, 90, 2.0),
        Candidata(3, 40, 3.0),
    ]
    assert elegir(candidatas, gastadas=2, libre=True, presupuesto=4) == [2, 3]


def test_presencia_y_presupuesto_son_puertas_reales():
    candidatas = [Candidata(1, 100, 1.0)]
    assert elegir(candidatas, gastadas=0, libre=False) == []
    assert elegir(candidatas, gastadas=4, libre=True) == []


def test_una_alerta_de_equipo_no_gasta_presupuesto_personal():
    candidatas = [
        Candidata(1, 10, 1.0),
        Candidata(2, 100, 2.0, fuera_presupuesto=True),
    ]
    assert elegir(candidatas, gastadas=4, libre=True) == [2]
    assert elegir(candidatas, gastadas=4, libre=False) == []
