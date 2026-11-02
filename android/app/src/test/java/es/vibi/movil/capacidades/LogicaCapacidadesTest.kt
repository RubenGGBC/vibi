package es.vibi.movil.capacidades

import es.vibi.movil.nodo.ErrorMovil
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class MediaLogicaTest {
    private val yt = SesionInfo("app.modificada.ytmusic", sonando = false)
    private val otra = SesionInfo("com.otra", sonando = true)

    @Test
    fun prefiere_sesion_guardada() {
        assertEquals(yt, elegirSesion(listOf(otra, yt), "app.modificada.ytmusic"))
    }

    @Test
    fun sin_guardada_usa_la_que_suena() {
        assertEquals(otra, elegirSesion(listOf(yt, otra), ""))
    }

    @Test
    fun sin_sesiones_lanza_sin_musica() {
        val error = assertThrows(ErrorMovil::class.java) { elegirSesion(emptyList(), "") }
        assertEquals("sin_musica", error.codigo)
    }

    @Test
    fun volumen_se_limita_al_rango() {
        assertEquals(15, indiceVolumen(150, 15))
        assertEquals(0, indiceVolumen(-5, 15))
        assertEquals(8, indiceVolumen(50, 15))
    }
}

class NotificacionesLogicaTest {
    private fun notif(
        id: String,
        app: String = "WhatsApp",
        paquete: String = "com.whatsapp",
        texto: String = "Hola",
        enCurso: Boolean = false,
        botones: List<String> = emptyList(),
    ) = NotifInfo(id, paquete, app, "Ana", texto, 1L, botones, enCurso)

    @Test
    fun filtra_por_app_y_limite() {
        val lista = listOf(notif("1"), notif("2"), notif("3", app = "Gmail", paquete = "com.gmail"))
        assertEquals(listOf("3"), filtrarNotificaciones(lista, "gmail", 10, "es.vibi.movil").map { it.id })
        assertEquals(2, filtrarNotificaciones(lista, null, 2, "es.vibi.movil").size)
    }

    @Test
    fun app_se_busca_sin_acentos() {
        val lista = listOf(notif("1", app = "Teléfono", paquete = "com.tel"))
        assertEquals(1, filtrarNotificaciones(lista, "telefono", 10, "es.vibi.movil").size)
    }

    @Test
    fun ignora_notificaciones_propias_y_en_curso() {
        val lista = listOf(
            notif("1", enCurso = true),
            notif("2", paquete = "es.vibi.movil"),
            notif("3"),
        )
        assertEquals(listOf("3"), filtrarNotificaciones(lista, null, 10, "es.vibi.movil").map { it.id })
    }

    @Test
    fun recorta_texto_largo() {
        val lista = listOf(notif("1", texto = "x".repeat(2_000)))
        val texto = filtrarNotificaciones(lista, null, 10, "p").single().texto
        assertTrue(texto.length <= 501)
    }

    @Test
    fun boton_inexistente_lanza_error() {
        val error = assertThrows(ErrorMovil::class.java) { indiceBoton(listOf("Responder"), "Borrar") }
        assertEquals("sin_boton", error.codigo)
    }

    @Test
    fun boton_se_encuentra_sin_mayusculas_ni_acentos() {
        assertEquals(1, indiceBoton(listOf("Responder", "Marcar como leído"), "marcar como leido"))
    }

    @Test
    fun sin_remote_input_lanza_sin_respuesta() {
        val error = assertThrows(ErrorMovil::class.java) { indiceRespuesta(listOf(false, false)) }
        assertEquals("sin_respuesta", error.codigo)
        assertEquals(1, indiceRespuesta(listOf(false, true)))
    }
}

class ArbolPantallaTest {
    private fun nodo(texto: String = "", clicable: Boolean = false, editable: Boolean = false) =
        NodoInfo("android.widget.Button", texto, clicable, editable, false)

    @Test
    fun serializa_solo_nodos_utiles() {
        val refs = ReferenciasPantalla<String>()
        val salida = refs.nuevaLectura(
            listOf(nodo() to "vacío", nodo("Aceptar", clicable = true) to "boton", nodo("Título") to "texto"),
        )
        assertEquals(listOf("Aceptar", "Título"), salida.map { it.texto })
        assertTrue(salida[0].clicable)
    }

    @Test
    fun limita_a_200_nodos() {
        val refs = ReferenciasPantalla<Int>()
        val salida = refs.nuevaLectura((0 until 500).map { nodo("n$it") to it })
        assertEquals(200, salida.size)
    }

    @Test
    fun ref_resuelve_el_elemento_de_la_lectura() {
        val refs = ReferenciasPantalla<String>()
        val salida = refs.nuevaLectura(listOf(nodo("Aceptar") to "boton"))
        assertEquals("boton", refs.resolver(salida[0].ref))
    }

    @Test
    fun ref_caducada_lanza_error() {
        val refs = ReferenciasPantalla<String>()
        val vieja = refs.nuevaLectura(listOf(nodo("A") to "a"))[0].ref
        refs.nuevaLectura(listOf(nodo("B") to "b"))
        val error = assertThrows(ErrorMovil::class.java) { refs.resolver(vieja) }
        assertEquals("ref_caducada", error.codigo)
    }

    @Test
    fun ref_invalida_lanza_error() {
        val refs = ReferenciasPantalla<String>()
        assertFalse(runCatching { refs.resolver("basura") }.isSuccess)
    }
}

class AppsLogicaTest {
    private val apps = listOf(
        AppInfo("Ajustes", "com.android.settings"),
        AppInfo("Música", "com.musica"),
        AppInfo("YT Music", "app.yt"),
        AppInfo("Google Chrome", "com.chrome"),
    )

    @Test
    fun resuelve_app_por_nombre_sin_acentos() {
        assertEquals("com.musica", resolverApp(apps, "musica").paquete)
    }

    @Test
    fun resuelve_por_coincidencia_parcial_unica() {
        assertEquals("com.chrome", resolverApp(apps, "chrome").paquete)
    }

    @Test
    fun nombre_ambiguo_devuelve_candidatas() {
        val error = assertThrows(ErrorMovil::class.java) { resolverApp(apps, "mus") }
        assertEquals("ambiguo", error.codigo)
        assertTrue(error.message!!.contains("YT Music"))
    }

    @Test
    fun nombre_inexistente_lanza_no_encontrada() {
        val error = assertThrows(ErrorMovil::class.java) { resolverApp(apps, "Tetris") }
        assertEquals("no_encontrada", error.codigo)
    }

    @Test
    fun enlace_se_detecta() {
        assertTrue(esEnlace("https://example.com"))
        assertFalse(esEnlace("Ajustes"))
    }
}
