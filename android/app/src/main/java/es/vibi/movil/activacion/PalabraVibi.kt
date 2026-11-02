package es.vibi.movil.activacion

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import es.vibi.movil.ajustes.Ajustes
import es.vibi.movil.ajustes.Microfono
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.io.File
import java.util.zip.ZipInputStream

private const val FRECUENCIA = 16_000
private const val SEGUNDOS_RECORDADOS = 3
private const val NOMBRE_MODELO = "vosk-model-small-es-0.42"
private const val URL_MODELO = "https://alphacephei.com/vosk/models/$NOMBRE_MODELO.zip"

/** La palabra «Vibi», detectada en el móvil. El audio no sale de aquí hasta despertar. */
class PalabraVibi(
    private val contexto: Context,
    private val ajustes: Ajustes,
    private val enLlamada: () -> Boolean,
    private val onDespertar: () -> Unit,
    private val onEstado: (String) -> Unit = {},
) {
    @Volatile private var activa = false
    private var ultimoDespertar = 0L
    private val hilo = HiloEscucha(
        cuerpo = { escuchar() },
        alDespertar = onDespertar,
        alFallar = {
            activa = false
            onEstado("La palabra «Vibi» no está disponible")
        },
    )

    fun arrancar() {
        activa = true
        hilo.arrancar()
    }

    fun parar() {
        activa = false
        hilo.esperar()
    }

    @SuppressLint("MissingPermission")
    private fun escuchar(): Boolean {
        val carpeta = asegurarModelo()
        if (!activa) return false
        val micCascos = ajustes.micEscucha == Microfono.CASCOS
        val audio = contexto.getSystemService(AudioManager::class.java)
        if (micCascos) {
            audio.mode = AudioManager.MODE_IN_COMMUNICATION
            audio.availableCommunicationDevices
                .firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
                ?.let { audio.setCommunicationDevice(it) }
        }
        val minimo = AudioRecord.getMinBufferSize(
            FRECUENCIA, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
        )
        val grabadora = AudioRecord(
            if (micCascos) MediaRecorder.AudioSource.VOICE_COMMUNICATION else MediaRecorder.AudioSource.MIC,
            FRECUENCIA,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minimo, FRECUENCIA),
        )
        return Model(carpeta.absolutePath).use { modelo ->
            Recognizer(modelo, FRECUENCIA.toFloat(), DetectorLogica.GRAMATICA).use { detector ->
                detector.setWords(true)
                grabadora.startRecording()
                try {
                    bucle(grabadora, modelo, detector)
                } finally {
                    grabadora.stop()
                    grabadora.release()
                    if (micCascos) {
                        audio.clearCommunicationDevice()
                        audio.mode = AudioManager.MODE_NORMAL
                    }
                }
            }
        }
    }

    /** `true` si ha oído la palabra; quien despierta lo hace ya sin micrófono. */
    private fun bucle(grabadora: AudioRecord, modelo: Model, detector: Recognizer): Boolean {
        val bloque = ByteArray(FRECUENCIA / 5 * 2)
        val recientes = ArrayDeque<ByteArray>()
        val maximoBloques = SEGUNDOS_RECORDADOS * 5
        while (activa) {
            val leidos = grabadora.read(bloque, 0, bloque.size)
            if (leidos <= 0) continue
            recientes.addLast(bloque.copyOf(leidos))
            if (recientes.size > maximoBloques) recientes.removeFirst()
            if (!detector.acceptWaveForm(bloque, leidos)) continue
            if (!oyoLaPalabra(detector.result)) continue
            val ahora = SystemClock.elapsedRealtime()
            if (!DetectorLogica.puedeDespertar(enLlamada(), ahora, ultimoDespertar)) continue
            if (confirmar(modelo, recientes)) {
                ultimoDespertar = ahora
                activa = false
                return true
            }
        }
        return false
    }

    private fun oyoLaPalabra(resultado: String): Boolean {
        val palabras = JSONObject(resultado).optJSONArray("result") ?: return false
        return (0 until palabras.length()).map { palabras.getJSONObject(it) }.any {
            DetectorLogica.candidato(it.optString("word"), it.optDouble("conf", 0.0))
        }
    }

    private fun confirmar(modelo: Model, recientes: ArrayDeque<ByteArray>): Boolean {
        Recognizer(modelo, FRECUENCIA.toFloat()).use { verificador ->
            recientes.forEach { verificador.acceptWaveForm(it, it.size) }
            return DetectorLogica.confirmado(JSONObject(verificador.finalResult).optString("text"))
        }
    }

    /** El modelo ocupa unos 40 MB: se baja la primera vez en lugar de engordar el APK. */
    private fun asegurarModelo(): File {
        val base = File(contexto.filesDir, "vosk")
        val destino = File(base, NOMBRE_MODELO)
        if (File(base, "$NOMBRE_MODELO.listo").exists()) return destino
        onEstado("Descargando el modelo de «Vibi»…")
        base.deleteRecursively()
        base.mkdirs()
        val raiz = base.canonicalPath + File.separator
        val peticion = Request.Builder().url(URL_MODELO).build()
        OkHttpClient().newCall(peticion).execute().use { respuesta ->
            check(respuesta.isSuccessful) { "No se pudo bajar el modelo: ${respuesta.code}" }
            ZipInputStream(respuesta.body!!.byteStream()).use { zip ->
                generateSequence { zip.nextEntry }.forEach { entrada ->
                    val archivo = File(base, entrada.name)
                    // Nada de un zip escribe fuera de su carpeta.
                    check(archivo.canonicalPath.startsWith(raiz)) { "Ruta no válida en el modelo" }
                    if (entrada.isDirectory) {
                        archivo.mkdirs()
                    } else {
                        archivo.parentFile?.mkdirs()
                        archivo.outputStream().use { zip.copyTo(it) }
                    }
                }
            }
        }
        File(base, "$NOMBRE_MODELO.listo").createNewFile()
        onEstado("En espera")
        return destino
    }
}
