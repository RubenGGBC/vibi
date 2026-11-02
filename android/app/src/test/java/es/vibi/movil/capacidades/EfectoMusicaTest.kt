package es.vibi.movil.capacidades

import es.vibi.movil.nodo.ErrorMovil
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class EfectoMusicaTest {
    private val sonando = EstadoMusica("A", true)
    private val pausada = EstadoMusica("A", false)

    @Test
    fun pausar_se_cumple_cuando_deja_de_sonar() {
        assertFalse(efectoCumplido("pausar", sonando, sonando))
        assertTrue(efectoCumplido("pausar", sonando, pausada))
    }

    @Test
    fun reanudar_se_cumple_cuando_suena() {
        assertFalse(efectoCumplido("reanudar", pausada, pausada))
        assertTrue(efectoCumplido("reanudar", pausada, sonando))
    }

    @Test
    fun siguiente_y_anterior_exigen_otra_cancion() {
        assertFalse(efectoCumplido("siguiente", sonando, sonando))
        assertTrue(efectoCumplido("siguiente", sonando, EstadoMusica("B", true)))
        assertTrue(efectoCumplido("anterior", sonando, EstadoMusica("B", true)))
    }

    @Test
    fun que_suena_y_avanzar_no_exigen_cambio() {
        assertTrue(efectoCumplido("que_suena", sonando, sonando))
        assertTrue(efectoCumplido("avanzar", sonando, sonando))
    }

    @Test
    fun cancion_concreta_exige_otra_cancion_sonando() {
        assertFalse(cancionCambiada("A", EstadoMusica("A", true)))
        assertFalse(cancionCambiada("A", EstadoMusica("B", false)))
        assertFalse(cancionCambiada("A", null))
        assertTrue(cancionCambiada("A", EstadoMusica("B", true)))
        assertTrue(cancionCambiada(null, EstadoMusica("B", true)))
    }

    @Test
    fun el_error_al_abrir_dice_por_que() {
        assertThrows(ErrorMovil::class.java) { throw errorAlAbrir(bloqueado = true) }
        assertEquals("bloqueado", errorAlAbrir(bloqueado = true).codigo)
        assertEquals("no_abre", errorAlAbrir(bloqueado = false).codigo)
    }
}
