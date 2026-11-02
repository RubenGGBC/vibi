package es.vibi.movil.voz

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReglasLlamadaTest {
    private fun cuelga(
        transcurrido: Long,
        delegando: Boolean = false,
        hablando: Boolean = false,
        vibiHablando: Boolean = false,
        silencio: Long = 10_000,
    ) = ReglasLlamada.debeColgar(
        ahora = 100_000 + transcurrido,
        ultimaVozVibi = 100_000,
        delegando = delegando,
        usuarioHablando = hablando,
        vibiHablando = vibiHablando,
        silencioMs = silencio,
    )

    @Test
    fun cuelga_a_los_10s_de_silencio() {
        assertFalse(cuelga(9_999))
        assertTrue(cuelga(10_000))
    }

    @Test
    fun no_cuelga_si_delega() {
        assertFalse(cuelga(60_000, delegando = true))
    }

    @Test
    fun no_cuelga_si_el_usuario_habla() {
        assertFalse(cuelga(60_000, hablando = true))
    }

    @Test
    fun no_cuelga_si_vibi_habla() {
        assertFalse(cuelga(60_000, vibiHablando = true))
    }

    @Test
    fun respeta_el_silencio_configurado() {
        assertTrue(cuelga(3_000, silencio = 3_000))
    }

    @Test
    fun nivel_de_salida_distingue_voz() {
        assertTrue(ReglasLlamada.hayVoz(0.05))
        assertFalse(ReglasLlamada.hayVoz(0.001))
    }
}
