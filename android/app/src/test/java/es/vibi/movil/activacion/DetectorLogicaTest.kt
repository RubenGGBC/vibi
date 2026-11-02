package es.vibi.movil.activacion

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DetectorLogicaTest {
    @Test
    fun bibi_confiado_es_candidato() {
        assertTrue(DetectorLogica.candidato("bibi", 0.9))
    }

    @Test
    fun baja_confianza_no_despierta() {
        assertFalse(DetectorLogica.candidato("bibi", 0.79))
    }

    @Test
    fun otra_palabra_no_es_candidata() {
        assertFalse(DetectorLogica.candidato("[unk]", 1.0))
    }

    @Test
    fun confirma_vivi_y_bibi() {
        assertTrue(DetectorLogica.confirmado("bibi"))
        assertTrue(DetectorLogica.confirmado("vivi"))
        assertTrue(DetectorLogica.confirmado("viví"))
        assertTrue(DetectorLogica.confirmado("vibi"))
    }

    @Test
    fun frase_ajena_no_confirma() {
        assertFalse(DetectorLogica.confirmado("yo vivo en madrid"))
        assertFalse(DetectorLogica.confirmado(""))
    }

    @Test
    fun no_despierta_durante_llamada() {
        assertFalse(DetectorLogica.puedeDespertar(enLlamada = true, ahora = 100_000, ultimoDespertar = 0))
    }

    @Test
    fun no_despierta_dos_veces_seguidas() {
        assertFalse(DetectorLogica.puedeDespertar(enLlamada = false, ahora = 1_000, ultimoDespertar = 0))
        assertTrue(DetectorLogica.puedeDespertar(enLlamada = false, ahora = 5_000, ultimoDespertar = 0))
    }
}
