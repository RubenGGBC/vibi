import pytest

from app import equipo_senales


def mensaje(nombre="avance", payload=None):
    return {
        "tipo": "senal_equipo",
        "id": "senal-1",
        "seguimiento": "seguimiento-1",
        "secuencia": 1,
        "senal": nombre,
        "payload": {} if payload is None else payload,
        "observada_en": 1_700_000_000.0,
        "schema": 1,
    }


def test_acepta_solo_el_payload_tipado():
    assert equipo_senales.validar(mensaje()).nombre == "avance"
    senal = equipo_senales.validar(mensaje("sin_avance", {"horas": 8}))
    assert senal.payload == {"horas": 8.0}


@pytest.mark.parametrize(
    "campo",
    ["contenido", "texto", "detalle", "ruta", "url", "ventana", "comando", "salida"],
)
def test_ninguna_senal_de_trabajo_transporta_contenido(campo):
    with pytest.raises(equipo_senales.SenalInvalida):
        equipo_senales.validar(mensaje(payload={campo: "secreto"}))


def test_rechaza_senal_inventada_y_campos_de_sobra():
    with pytest.raises(equipo_senales.SenalInvalida):
        equipo_senales.validar(mensaje("productividad"))
    crudo = mensaje()
    crudo["persona"] = "dani"
    with pytest.raises(equipo_senales.SenalInvalida):
        equipo_senales.validar(crudo)

