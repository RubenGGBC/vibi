package es.vibi.movil.voz

import es.vibi.movil.activacion.HiloEscucha
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class TiemposApiVozTest {
    private fun conServidorMudo(prueba: (ApiVoz) -> Unit) {
        val servidor = MockWebServer()
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        servidor.start()
        try {
            prueba(ApiVoz(servidor.url("/").toString().trimEnd('/'), "token"))
        } finally {
            servidor.shutdown()
        }
    }

    @Test
    fun sondeo_no_espera_mas_de_unos_segundos() = conServidorMudo { api ->
        val inicio = System.currentTimeMillis()
        assertThrows(IOException::class.java) { api.eventos("c1") }
        assertTrue(System.currentTimeMillis() - inicio < 6_000)
    }

    @Test
    fun colgar_no_espera_mas_de_unos_segundos() = conServidorMudo { api ->
        val inicio = System.currentTimeMillis()
        assertThrows(IOException::class.java) { api.colgar() }
        assertTrue(System.currentTimeMillis() - inicio < 6_000)
    }
}

class CierreLlamadaTest {
    @Test
    fun la_musica_vuelve_antes_de_avisar_al_servidor() {
        val pasos = mutableListOf<String>()
        cerrarLlamada(
            liberar = { pasos.add("liberar") },
            restaurar = { pasos.add("restaurar") },
            avisar = { pasos.add("avisar") },
        )
        assertEquals(listOf("liberar", "restaurar", "avisar"), pasos)
    }

    @Test
    fun un_fallo_al_liberar_no_impide_restaurar() {
        val pasos = mutableListOf<String>()
        cerrarLlamada(
            liberar = { error("webrtc") },
            restaurar = { pasos.add("restaurar") },
            avisar = { pasos.add("avisar") },
        )
        assertEquals(listOf("restaurar", "avisar"), pasos)
    }
}

class EstadoLlamadaTest {
    @Test
    fun error_no_se_pisa_al_terminar() {
        val publicados = mutableListOf<String>()
        val estado = EstadoLlamada { publicados.add(it) }
        estado.error("Se ha agotado el límite")
        estado.terminar()
        assertEquals("Se ha agotado el límite", publicados.last())
    }

    @Test
    fun sin_error_vuelve_a_espera() {
        val publicados = mutableListOf<String>()
        val estado = EstadoLlamada { publicados.add(it) }
        estado.publicar("Te escucho")
        estado.terminar()
        assertEquals("En espera", publicados.last())
    }

    @Test
    fun el_error_se_olvida_en_la_siguiente_llamada() {
        val publicados = mutableListOf<String>()
        val estado = EstadoLlamada { publicados.add(it) }
        estado.error("Fallo")
        estado.terminar()
        estado.publicar("Conectando…")
        estado.terminar()
        assertEquals("En espera", publicados.last())
    }

    @Test
    fun tras_apagar_no_publica_nada() {
        val publicados = mutableListOf<String>()
        val estado = EstadoLlamada { publicados.add(it) }
        estado.apagar()
        estado.publicar("Te escucho")
        estado.error("Fallo")
        estado.terminar()
        assertTrue(publicados.isEmpty())
    }
}

class HerramientasEnCursoTest {
    @Test
    fun una_tarea_lenta_sigue_en_curso_aunque_termine_otra() {
        val herramientas = HerramientasEnCurso()
        herramientas.empieza()
        herramientas.empieza()
        herramientas.termina()
        assertTrue(herramientas.hay)
        herramientas.termina()
        assertFalse(herramientas.hay)
    }

    @Test
    fun un_resultado_de_mas_no_descuadra() {
        val herramientas = HerramientasEnCurso()
        herramientas.termina()
        herramientas.empieza()
        assertTrue(herramientas.hay)
    }
}

class HiloEscuchaTest {
    @Test
    fun despierta_despues_de_liberar_el_microfono() {
        val pasos = mutableListOf<String>()
        val hecho = CountDownLatch(1)
        val hilo = HiloEscucha(
            cuerpo = {
                pasos.add("microfono liberado")
                true
            },
            alDespertar = {
                pasos.add("despertar")
                hecho.countDown()
            },
        )
        hilo.arrancar()
        assertTrue(hecho.await(2, TimeUnit.SECONDS))
        assertEquals(listOf("microfono liberado", "despertar"), pasos)
    }

    @Test
    fun tras_un_fallo_se_puede_volver_a_arrancar() {
        val intentos = CountDownLatch(2)
        val hilo = HiloEscucha(
            cuerpo = {
                intentos.countDown()
                error("sin modelo")
            },
            alDespertar = {},
        )
        hilo.arrancar()
        hilo.esperar()
        hilo.arrancar()
        assertTrue(intentos.await(2, TimeUnit.SECONDS))
    }

    @Test
    fun parar_sin_despertar_no_avisa() {
        var avisos = 0
        val hilo = HiloEscucha(cuerpo = { false }, alDespertar = { avisos++ })
        hilo.arrancar()
        hilo.esperar()
        assertEquals(0, avisos)
        assertNull(hilo.fallo)
    }
}
