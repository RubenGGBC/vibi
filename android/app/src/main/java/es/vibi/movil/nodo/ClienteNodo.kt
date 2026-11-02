package es.vibi.movil.nodo

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlin.random.Random

private const val BASE_MS = 1_000L
private const val TOPE_MS = 60_000L
private const val CIERRE_TOKEN_INVALIDO = 4401
private const val CIERRE_SUSTITUIDA = 4409

/** Backoff exponencial con jitter, con tope de 60 s, igual que el agente de escritorio. */
fun esperaReconexion(intento: Int, jitter: Double = Random.nextDouble()): Long {
    val exponencial = BASE_MS shl min(intento, 16)
    val conJitter = (exponencial * (1 + jitter * 0.25)).toLong()
    return min(conJitter, TOPE_MS)
}

/** Con el token revocado o sustituido, insistir solo expulsaría a la otra conexión. */
fun debeReconectar(codigoCierre: Int): Boolean =
    codigoCierre != CIERRE_TOKEN_INVALIDO && codigoCierre != CIERRE_SUSTITUIDA

/** La mitad del móvil del protocolo de `/api/nodos/ws`. */
class ClienteNodo(
    baseUrl: String,
    private val token: String,
    capacidades: List<Capacidad>,
    private val onNotificacion: (String) -> Unit = {},
    private val onEstado: (Boolean) -> Unit = {},
    private val cliente: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(25, TimeUnit.SECONDS)
        .build(),
) {
    private val url = baseUrl.trimEnd('/') + "/api/nodos/ws"
    private val porNombre = capacidades.associateBy { it.nombre }
    private val alcance = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val planificador = Executors.newSingleThreadScheduledExecutor()
    private val cerrojo = Any()

    private var socket: WebSocket? = null
    private var reintento: ScheduledFuture<*>? = null
    private var intento = 0
    private var parado = false

    fun conectar() {
        synchronized(cerrojo) {
            if (parado || socket != null) return
            val peticion = Request.Builder().url(url).build()
            socket = cliente.newWebSocket(peticion, Oyente())
        }
    }

    fun parar() {
        synchronized(cerrojo) {
            parado = true
            reintento?.cancel(false)
            socket?.close(1000, "Parado")
            socket = null
        }
        alcance.cancel()
        planificador.shutdownNow()
        onEstado(false)
    }

    private fun alCaer(ws: WebSocket, codigo: Int) {
        synchronized(cerrojo) {
            if (socket !== ws) return
            socket = null
            onEstado(false)
            if (parado || !debeReconectar(codigo)) return
            val espera = esperaReconexion(intento++)
            reintento = planificador.schedule({ conectar() }, espera, TimeUnit.MILLISECONDS)
        }
    }

    private fun atender(ws: WebSocket, orden: JSONObject) {
        val id = orden.optString("id")
        val nombre = orden.optString("capability")
        val argumentos = orden.optJSONObject("arguments") ?: JSONObject()
        alcance.launch {
            val respuesta = JSONObject().put("tipo", "resultado").put("id", id)
            try {
                val capacidad = porNombre[nombre]
                    ?: throw ErrorMovil("no_soportada", "El móvil no sabe hacer $nombre")
                respuesta.put("estado", "ok").put("resultado", capacidad.ejecutar(argumentos))
            } catch (error: ErrorMovil) {
                respuesta.put("estado", "error").put(
                    "resultado",
                    JSONObject().put("codigo", error.codigo).put("error", error.message),
                )
            } catch (error: Exception) {
                // Un fallo local nunca tumba el nodo: se cuenta y se sigue.
                respuesta.put("estado", "error").put(
                    "resultado",
                    JSONObject().put("codigo", "interno")
                        .put("error", "El móvil ha fallado al hacerlo."),
                )
            }
            ws.send(respuesta.toString())
        }
    }

    private inner class Oyente : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            val hola = JSONObject().put("tipo", "hola").put("token", token)
                .put("capacidades", JSONArray(porNombre.keys.toList()))
            webSocket.send(hola.toString())
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val mensaje = runCatching { JSONObject(text) }.getOrNull() ?: return
            when (mensaje.optString("tipo")) {
                "conexion_lista" -> {
                    intento = 0
                    onEstado(true)
                }
                "orden" -> atender(webSocket, mensaje)
                "notificacion" -> onNotificacion(mensaje.optString("texto"))
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(code.coerceIn(1000, 4999), null)
            alCaer(webSocket, code)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            alCaer(webSocket, code)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            alCaer(webSocket, 1006)
        }
    }
}
