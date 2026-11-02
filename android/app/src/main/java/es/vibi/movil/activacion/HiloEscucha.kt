package es.vibi.movil.activacion

import android.util.Log
import kotlin.concurrent.thread

/**
 * El hilo de la escucha. Avisa de un despertar solo cuando `cuerpo` ha terminado, con el
 * micrófono y la ruta de audio ya liberados, para que la llamada no compita con ellos.
 */
class HiloEscucha(
    private val cuerpo: () -> Boolean,
    private val alDespertar: () -> Unit,
    private val alFallar: (Exception) -> Unit = {},
) {
    private var hilo: Thread? = null

    @Volatile
    var fallo: Exception? = null
        private set

    @Synchronized
    fun arrancar() {
        if (hilo?.isAlive == true) return
        fallo = null
        hilo = thread(name = "vibi-palabra") {
            val desperto = try {
                cuerpo()
            } catch (error: Exception) {
                runCatching { Log.w("VibiPalabra", "La escucha ha fallado", error) }
                fallo = error
                alFallar(error)
                false
            }
            if (desperto) alDespertar()
        }
    }

    fun esperar(ms: Long = 2_000) {
        val actual = synchronized(this) { hilo } ?: return
        if (Thread.currentThread() !== actual) actual.join(ms)
    }
}
