package es.vibi.movil.capacidades

import android.app.KeyguardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import es.vibi.movil.ajustes.Ajustes
import es.vibi.movil.nodo.Capacidad
import es.vibi.movil.nodo.ErrorMovil
import es.vibi.movil.servicio.OyenteNotificaciones
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

private const val ESPERA_CAMBIO_MS = 3_000L
private const val AVANCE_MS = 15_000L
private const val ESPERA_EFECTO_MS = 1_500L
private const val ESPERA_APERTURA_MS = 6_000L

/** Las sesiones de música del móvil. La APK se identifica por su sesión, nunca por su nombre. */
class SesionesMusica(private val contexto: Context, private val ajustes: Ajustes) {
    fun activas(): List<MediaController> = try {
        contexto.getSystemService(MediaSessionManager::class.java)
            .getActiveSessions(ComponentName(contexto, OyenteNotificaciones::class.java))
    } catch (error: SecurityException) {
        throw ErrorMovil("sin_permiso", "Falta conceder a Vibi el acceso a notificaciones.")
    }

    fun elegida(): MediaController {
        val sesiones = activas()
        val info = elegirSesion(
            sesiones.map { SesionInfo(it.packageName, estaSonando(it)) },
            ajustes.paqueteMusica,
        )
        return sesiones.first { it.packageName == info.paquete }
    }

    /** Lo que suena ahora pasa a ser la app de música de Vibi. */
    fun recordarLaQueSuena(): String? =
        activas().firstOrNull(::estaSonando)?.packageName?.also { ajustes.paqueteMusica = it }

    fun estaSonando(sesion: MediaController) =
        sesion.playbackState?.state == PlaybackState.STATE_PLAYING
}

private fun titulo(sesion: MediaController): String? =
    sesion.metadata?.getString(MediaMetadata.METADATA_KEY_TITLE)

private fun estado(sesion: MediaController) = EstadoMusica(
    titulo(sesion),
    sesion.playbackState?.state == PlaybackState.STATE_PLAYING,
)

private fun descripcion(sesion: MediaController, sonando: Boolean): JSONObject =
    JSONObject()
        .put("titulo", titulo(sesion) ?: JSONObject.NULL)
        .put("artista", sesion.metadata?.getString(MediaMetadata.METADATA_KEY_ARTIST) ?: JSONObject.NULL)
        .put("sonando", sonando)

class CapacidadMedia(private val sesiones: SesionesMusica) : Capacidad {
    override val nombre = "movil.media"

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        val sesion = sesiones.elegida()
        val controles = sesion.transportControls
        val accion = args.optString("accion")
        val antes = estado(sesion)
        when (accion) {
            "pausar" -> controles.pause()
            "reanudar" -> controles.play()
            "siguiente" -> controles.skipToNext()
            "anterior" -> controles.skipToPrevious()
            "avanzar" -> {
                val posicion = sesion.playbackState?.position ?: 0
                val salto = if (args.has("segundos")) args.getLong("segundos") * 1000 else AVANCE_MS
                controles.seekTo(posicion + salto)
            }
            "que_suena" -> Unit
            else -> throw ErrorMovil("accion_desconocida", "No sé hacer «$accion» con la música.")
        }
        // Los controles son asíncronos: leer justo después devolvería la canción anterior.
        val cumplido = withTimeoutOrNull(ESPERA_EFECTO_MS) {
            while (!efectoCumplido(accion, antes, estado(sesion))) delay(50)
            true
        }
        if (cumplido != true) throw ErrorMovil("sin_efecto", "La app de música no ha hecho caso.")
        return descripcion(sesion, sesiones.estaSonando(sesion))
    }
}

class CapacidadReproducir(
    private val contexto: Context,
    private val ajustes: Ajustes,
    private val sesiones: SesionesMusica,
) : Capacidad {
    override val nombre = "movil.media.reproducir"

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        val video = args.optString("video_id")
        if (video.isNotEmpty()) return abrirCancion(video)
        return buscarEnLaSesion(args.optString("consulta"))
    }

    /** `no_soportado` no es un fallo: le dice al servidor que busque él y mande el ID. */
    private suspend fun buscarEnLaSesion(consulta: String): JSONObject {
        val sesion = runCatching { sesiones.elegida() }.getOrNull()
            ?: throw ErrorMovil("no_soportado", "No hay sesión a la que pedírselo.")
        val acciones = sesion.playbackState?.actions ?: 0
        if (acciones and PlaybackState.ACTION_PLAY_FROM_SEARCH == 0L) {
            throw ErrorMovil("no_soportado", "Esta app no acepta búsquedas.")
        }
        val anterior = titulo(sesion)
        sesion.transportControls.playFromSearch(consulta, Bundle())
        val cambiada = withTimeoutOrNull(ESPERA_CAMBIO_MS) {
            while (titulo(sesion) == anterior) delay(100)
            true
        }
        if (cambiada != true) throw ErrorMovil("no_soportado", "La app no ha cambiado de canción.")
        return descripcion(sesion, sesiones.estaSonando(sesion))
    }

    private suspend fun abrirCancion(video: String): JSONObject {
        val paquete = ajustes.paqueteMusica.ifEmpty {
            runCatching { sesiones.elegida().packageName }.getOrNull()
        } ?: throw ErrorMovil("sin_app", "Abre tu app de música y pulsa «Usar esta app de música».")
        if (!Settings.canDrawOverlays(contexto)) {
            throw ErrorMovil("sin_permiso", "Falta conceder a Vibi «mostrar sobre otras apps».")
        }
        val anterior = runCatching { titulo(sesiones.elegida()) }.getOrNull()
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("https://music.youtube.com/watch?v=$video"))
            .setPackage(paquete)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            contexto.startActivity(intent)
        } catch (error: Exception) {
            throw ErrorMovil("no_abre", "Tu app de música no ha podido abrir la canción.")
        }
        // Android bloquea sin avisar lo que se abre desde segundo plano: solo cuenta oírla.
        val sonando = withTimeoutOrNull(ESPERA_APERTURA_MS) {
            while (true) {
                val sesion = runCatching { sesiones.elegida() }.getOrNull()
                if (sesion != null && cancionCambiada(anterior, estado(sesion))) return@withTimeoutOrNull sesion
                delay(200)
            }
            @Suppress("UNREACHABLE_CODE")
            null
        }
        if (sonando == null) {
            throw errorAlAbrir(contexto.getSystemService(KeyguardManager::class.java).isKeyguardLocked)
        }
        return descripcion(sonando, true)
    }
}

class CapacidadVolumen(contexto: Context) : Capacidad {
    override val nombre = "movil.volumen"
    private val audio = contexto.getSystemService(AudioManager::class.java)

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        val canal = AudioManager.STREAM_MUSIC
        val maximo = audio.getStreamMaxVolume(canal)
        when (val accion = args.optString("accion")) {
            "leer" -> Unit
            "poner" -> {
                if (!args.has("nivel")) throw ErrorMovil("sin_nivel", "Dime a qué nivel lo pongo.")
                audio.setStreamVolume(canal, indiceVolumen(args.getInt("nivel"), maximo), 0)
            }
            "subir" -> audio.adjustStreamVolume(canal, AudioManager.ADJUST_RAISE, 0)
            "bajar" -> audio.adjustStreamVolume(canal, AudioManager.ADJUST_LOWER, 0)
            else -> throw ErrorMovil("accion_desconocida", "No sé hacer «$accion» con el volumen.")
        }
        return JSONObject().put("nivel", audio.getStreamVolume(canal) * 100 / maximo)
    }
}
