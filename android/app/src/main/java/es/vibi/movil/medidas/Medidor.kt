package es.vibi.movil.medidas

import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject

private const val MAX_SESIONES = 100

/** Las marcas de tiempo de cada activación: sin estas cifras la prueba no sirve. */
class Medidor(private val reloj: () -> Long = { SystemClock.elapsedRealtime() }) {
    private class Sesion(val origen: String, val inicio: Long) {
        val eventos = linkedMapOf("deteccion" to 0L)
        val ordenes = JSONArray()
    }

    private val sesiones = ArrayDeque<Sesion>()

    @Synchronized
    fun nuevaSesion(origen: String, ahora: Long = reloj()) {
        sesiones.addLast(Sesion(origen, ahora))
        if (sesiones.size > MAX_SESIONES) sesiones.removeFirst()
    }

    @Synchronized
    fun marcar(evento: String, ahora: Long = reloj()) {
        val sesion = sesiones.lastOrNull() ?: return
        sesion.eventos.putIfAbsent(evento, ahora - sesion.inicio)
    }

    @Synchronized
    fun marcarOrden(capacidad: String, duracionMs: Long) {
        val sesion = sesiones.lastOrNull() ?: return
        sesion.ordenes.put(JSONObject().put("capacidad", capacidad).put("ms", duracionMs))
    }

    @Synchronized
    fun exportarJson(): String {
        val salida = JSONArray()
        for (sesion in sesiones) {
            val tiempos = JSONObject()
            sesion.eventos.forEach { (evento, ms) -> tiempos.put(evento, ms) }
            salida.put(
                JSONObject().put("origen", sesion.origen).put("ms", tiempos)
                    .put("ordenes", sesion.ordenes),
            )
        }
        return salida.toString(2)
    }
}
