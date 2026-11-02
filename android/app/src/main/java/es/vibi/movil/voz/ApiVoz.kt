package es.vibi.movil.voz

import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class RespuestaLlamada(val sdp: String, val conversationId: String)

class EventosLlamada(val activa: Boolean, val eventos: List<JSONObject>)

/** Las tres peticiones de una llamada: abrir, preguntar qué pasa y colgar. */
class ApiVoz(private val baseUrl: String, private val token: String) {
    private val json = "application/json".toMediaType()
    private val cliente = OkHttpClient.Builder()
        // Abrir la llamada arranca un proceso de Codex: el servidor espera hasta 55 s.
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    /** Sondear y colgar no pueden retener la música si la red se ha caído. */
    private val rapido = cliente.newBuilder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.SECONDS)
        .writeTimeout(3, TimeUnit.SECONDS)
        .callTimeout(4, TimeUnit.SECONDS)
        .build()

    private fun peticion(ruta: String) = Request.Builder()
        .url(baseUrl + ruta)
        .header("Authorization", "Bearer $token")

    private fun ejecutar(peticion: Request, conQuien: OkHttpClient = rapido): JSONObject {
        conQuien.newCall(peticion).execute().use { respuesta ->
            val cuerpo = respuesta.body?.string().orEmpty()
            if (!respuesta.isSuccessful) {
                val detalle = runCatching { JSONObject(cuerpo).optString("detail") }.getOrNull()
                throw IOException(detalle?.ifEmpty { null } ?: "El servidor respondió ${respuesta.code}")
            }
            return JSONObject(cuerpo)
        }
    }

    fun abrir(sdp: String, voz: String = "maple"): RespuestaLlamada {
        val cuerpo = JSONObject().put("sdp", sdp).put("voz", voz).toString().toRequestBody(json)
        val respuesta = ejecutar(peticion("/api/voz/movil/llamada").post(cuerpo).build(), cliente)
        return RespuestaLlamada(respuesta.getString("sdp"), respuesta.getString("conversation_id"))
    }

    fun eventos(conversationId: String): EventosLlamada {
        val url = (baseUrl + "/api/voz/codex/eventos").toHttpUrl().newBuilder()
            .addQueryParameter("conversation_id", conversationId).build()
        val respuesta = ejecutar(
            Request.Builder().url(url).header("Authorization", "Bearer $token").build(),
        )
        val lista = respuesta.optJSONArray("eventos")
        val eventos = List(lista?.length() ?: 0) { lista!!.getJSONObject(it) }
        return EventosLlamada(respuesta.optBoolean("activa"), eventos)
    }

    fun colgar() {
        ejecutar(peticion("/api/voz/movil/colgar").post("{}".toRequestBody(json)).build())
    }
}
