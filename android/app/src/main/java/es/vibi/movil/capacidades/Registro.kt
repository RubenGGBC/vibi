package es.vibi.movil.capacidades

import android.content.Context
import es.vibi.movil.ajustes.Ajustes
import es.vibi.movil.medidas.Medidor
import es.vibi.movil.nodo.Capacidad
import org.json.JSONObject

/** Todo lo que el móvil declara al servidor. Cada orden deja su duración en las medidas. */
object Registro {
    fun todas(contexto: Context, ajustes: Ajustes, medidor: Medidor): List<Capacidad> =
        emptyList<Capacidad>().map { Medida(it, medidor) }

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
