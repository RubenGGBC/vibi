package es.vibi.movil.nodo

import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

class ClienteNodoTest {
    private lateinit var servidor: MockWebServer
    private val recibidos = LinkedBlockingQueue<JSONObject>()
    private val abiertos = LinkedBlockingQueue<WebSocket>()
    private val todos = LinkedBlockingQueue<WebSocket>()
    private var cliente: ClienteNodo? = null

    private val eco = object : Capacidad {
        override val nombre = "movil.media"
        override suspend fun ejecutar(args: JSONObject) =
            JSONObject().put("eco", args.getString("accion"))
    }
    private val rota = object : Capacidad {
        override val nombre = "movil.volumen"
        override suspend fun ejecutar(args: JSONObject): JSONObject =
            throw ErrorMovil("sin_musica", "No suena nada")
    }
    private val inesperada = object : Capacidad {
        override val nombre = "movil.apps.abrir"
        override suspend fun ejecutar(args: JSONObject): JSONObject =
            throw IllegalStateException("boom")
    }

    private fun escuchar() = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            abiertos.add(webSocket)
            todos.add(webSocket)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            recibidos.add(JSONObject(text))
        }
    }

    @Before
    fun arrancar() {
        servidor = MockWebServer()
        servidor.start()
    }

    @After
    fun parar() {
        cliente?.parar()
        todos.forEach { it.close(1000, null) }
        Thread.sleep(200)
        servidor.shutdown()
    }

    private fun conectar(aviso: (String) -> Unit = {}): WebSocket {
        servidor.enqueue(MockResponse().withWebSocketUpgrade(escuchar()))
        cliente = ClienteNodo(
            baseUrl = servidor.url("/").toString().trimEnd('/'),
            token = "n1.secreto",
            capacidades = listOf(eco, rota, inesperada),
            onNotificacion = aviso,
        )
        cliente!!.conectar()
        return abiertos.poll(5, TimeUnit.SECONDS)!!
    }

    private fun orden(id: String, capacidad: String, accion: String = "pausar") =
        JSONObject().put("tipo", "orden").put("id", id).put("capability", capacidad)
            .put("arguments", JSONObject().put("accion", accion)).toString()

    private fun siguiente() = recibidos.poll(5, TimeUnit.SECONDS)!!

    @Test
    fun saluda_con_token_y_capacidades() {
        conectar()
        val hola = siguiente()
        assertEquals("hola", hola.getString("tipo"))
        assertEquals("n1.secreto", hola.getString("token"))
        assertEquals(3, hola.getJSONArray("capacidades").length())
        assertEquals("/api/nodos/ws", servidor.takeRequest().path)
    }

    @Test
    fun orden_devuelve_resultado_ok() {
        val ws = conectar()
        siguiente()
        ws.send(orden("o1", "movil.media"))
        val resultado = siguiente()
        assertEquals("resultado", resultado.getString("tipo"))
        assertEquals("o1", resultado.getString("id"))
        assertEquals("ok", resultado.getString("estado"))
        assertEquals("pausar", resultado.getJSONObject("resultado").getString("eco"))
    }

    @Test
    fun error_movil_devuelve_su_codigo() {
        val ws = conectar()
        siguiente()
        ws.send(orden("o2", "movil.volumen"))
        val resultado = siguiente()
        assertEquals("error", resultado.getString("estado"))
        assertEquals("sin_musica", resultado.getJSONObject("resultado").getString("codigo"))
        assertEquals("No suena nada", resultado.getJSONObject("resultado").getString("error"))
    }

    @Test
    fun excepcion_devuelve_error_sin_caerse() {
        val ws = conectar()
        siguiente()
        ws.send(orden("o3", "movil.apps.abrir"))
        assertEquals("error", siguiente().getString("estado"))
        ws.send(orden("o4", "movil.media"))
        assertEquals("ok", siguiente().getString("estado"))
    }

    @Test
    fun capacidad_desconocida_devuelve_error() {
        val ws = conectar()
        siguiente()
        ws.send(orden("o5", "shell.run"))
        val resultado = siguiente()
        assertEquals("error", resultado.getString("estado"))
        assertEquals("o5", resultado.getString("id"))
    }

    @Test
    fun notificacion_llega_al_callback() {
        val avisos = LinkedBlockingQueue<String>()
        val ws = conectar { avisos.add(it) }
        ws.send(JSONObject().put("tipo", "notificacion").put("texto", "Tarea lista").toString())
        assertEquals("Tarea lista", avisos.poll(5, TimeUnit.SECONDS))
    }

    @Test
    fun reconecta_con_backoff_hasta_60s() {
        assertEquals(1_000L, esperaReconexion(0, jitter = 0.0))
        assertEquals(2_000L, esperaReconexion(1, jitter = 0.0))
        assertEquals(60_000L, esperaReconexion(30, jitter = 0.0))
        assertTrue(esperaReconexion(30, jitter = 1.0) <= 60_000L)
        assertTrue(esperaReconexion(1, jitter = 0.5) > 2_000L)
    }

    @Test
    fun reconecta_de_verdad_al_caer() {
        val ws = conectar()
        siguiente()
        servidor.enqueue(MockResponse().withWebSocketUpgrade(escuchar()))
        ws.close(1011, "reinicio")
        assertNotNull(abiertos.poll(10, TimeUnit.SECONDS))
    }

    @Test
    fun parar_no_reconecta() {
        conectar()
        siguiente()
        cliente!!.parar()
        servidor.enqueue(MockResponse().withWebSocketUpgrade(escuchar()))
        Thread.sleep(1_500)
        assertNull(abiertos.poll(0, TimeUnit.SECONDS))
    }

    @Test
    fun token_revocado_no_reconecta() {
        assertFalse(debeReconectar(codigoCierre = 4401))
        assertFalse(debeReconectar(codigoCierre = 4409))
        assertTrue(debeReconectar(codigoCierre = 1011))
    }
}
