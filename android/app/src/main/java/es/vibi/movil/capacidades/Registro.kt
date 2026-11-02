package es.vibi.movil.capacidades

import android.content.Context
import android.view.accessibility.AccessibilityNodeInfo
import es.vibi.movil.ajustes.Ajustes
import es.vibi.movil.medidas.Medidor
import es.vibi.movil.nodo.Capacidad
import org.json.JSONObject

/** Todo lo que el móvil declara al servidor. Cada orden deja su duración en las medidas. */
object Registro {
    fun todas(contexto: Context, ajustes: Ajustes, medidor: Medidor): List<Capacidad> {
        val sesiones = SesionesMusica(contexto, ajustes)
        val referencias = ReferenciasPantalla<AccessibilityNodeInfo>()
        return listOf(
            CapacidadMedia(sesiones),
            CapacidadReproducir(contexto, ajustes, sesiones),
            CapacidadVolumen(contexto),
            CapacidadListarNotificaciones(contexto),
            CapacidadDescartarNotificacion(contexto),
            CapacidadPulsarNotificacion(contexto),
            CapacidadResponderNotificacion(contexto),
            CapacidadAbrirApp(contexto),
            CapacidadLeerPantalla(contexto, referencias),
            CapacidadActuarPantalla(contexto, referencias),
        ).map { Medida(it, medidor) }
    }

    private class Medida(private val interna: Capacidad, private val medidor: Medidor) : Capacidad {
        override val nombre = interna.nombre

        override suspend fun ejecutar(args: JSONObject): JSONObject {
            val inicio = System.currentTimeMillis()
            try {
                return interna.ejecutar(args)
            } finally {
                medidor.marcarOrden(nombre, System.currentTimeMillis() - inicio)
            }
        }
    }
}
