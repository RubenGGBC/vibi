package es.vibi.movil.medidas

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class MedidorTest {
    @Test
    fun medidor_calcula_intervalos_en_orden() {
        val medidor = Medidor()
        medidor.nuevaSesion("boton", ahora = 1_000)
        medidor.marcar("ping", ahora = 1_100)
        medidor.marcar("sdp", ahora = 2_500)
        val sesion = JSONArray(medidor.exportarJson()).getJSONObject(0)
        assertEquals("boton", sesion.getString("origen"))
        val eventos = sesion.getJSONObject("ms")
        assertEquals(0, eventos.getLong("deteccion"))
        assertEquals(100, eventos.getLong("ping"))
        assertEquals(1_500, eventos.getLong("sdp"))
    }

    @Test
    fun medidor_exporta_sesion_incompleta() {
        val medidor = Medidor()
        medidor.nuevaSesion("palabra", ahora = 5)
        val sesion = JSONArray(medidor.exportarJson()).getJSONObject(0)
        assertFalse(sesion.getJSONObject("ms").has("sdp"))
    }

    @Test
    fun repetir_un_evento_conserva_el_primero() {
        val medidor = Medidor()
        medidor.nuevaSesion("boton", ahora = 0)
        medidor.marcar("primera_voz", ahora = 10)
        medidor.marcar("primera_voz", ahora = 20)
        val sesion = JSONArray(medidor.exportarJson()).getJSONObject(0)
        assertEquals(10, sesion.getJSONObject("ms").getLong("primera_voz"))
    }

    @Test
    fun orden_y_resultado_se_acumulan_por_llamada() {
        val medidor = Medidor()
        medidor.nuevaSesion("boton", ahora = 0)
        medidor.marcarOrden("movil.media", duracionMs = 80)
        val sesion = JSONArray(medidor.exportarJson()).getJSONObject(0)
        val orden = sesion.getJSONArray("ordenes").getJSONObject(0)
        assertEquals("movil.media", orden.getString("capacidad"))
        assertEquals(80, orden.getLong("ms"))
    }

    @Test
    fun cada_turno_guarda_su_fin_de_frase() {
        val medidor = Medidor()
        medidor.nuevaSesion("boton", ahora = 100)
        medidor.marcarFinFrase(ahora = 1_100)
        medidor.marcarFinFrase(ahora = 5_100)
        val frases = JSONArray(medidor.exportarJson()).getJSONObject(0).getJSONArray("fin_frase")
        assertEquals(1_000, frases.getLong(0))
        assertEquals(5_000, frases.getLong(1))
    }

    @Test
    fun cada_orden_guarda_cuando_empezo() {
        val medidor = Medidor()
        medidor.nuevaSesion("boton", ahora = 100)
        medidor.marcarOrden("movil.media", duracionMs = 80, ahora = 600)
        medidor.marcarOrden("movil.volumen", duracionMs = 10, ahora = 900)
        val ordenes = JSONArray(medidor.exportarJson()).getJSONObject(0).getJSONArray("ordenes")
        assertEquals(500, ordenes.getJSONObject(0).getLong("inicio"))
        assertEquals(800, ordenes.getJSONObject(1).getLong("inicio"))
    }

    @Test
    fun el_error_queda_en_la_sesion() {
        val medidor = Medidor()
        medidor.nuevaSesion("boton", ahora = 0)
        medidor.marcarError("Límite agotado")
        val sesion = JSONArray(medidor.exportarJson()).getJSONObject(0)
        assertEquals("Límite agotado", sesion.getString("error"))
    }

    @Test
    fun sin_sesion_marcar_no_falla() {
        val medidor = Medidor()
        medidor.marcar("ping", ahora = 1)
        assertEquals(0, JSONArray(medidor.exportarJson()).length())
    }

    @Test
    fun conserva_como_maximo_cien_sesiones() {
        val medidor = Medidor()
        repeat(120) { medidor.nuevaSesion("boton", ahora = it.toLong()) }
        assertEquals(100, JSONArray(medidor.exportarJson()).length())
    }
}
