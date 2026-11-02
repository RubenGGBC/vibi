package es.vibi.movil.nodo

import org.json.JSONObject

/** Algo que el móvil sabe hacer cuando el servidor se lo pide. */
interface Capacidad {
    val nombre: String
    suspend fun ejecutar(args: JSONObject): JSONObject
}

/** Un fallo que Vibi debe poder contar por voz, con un código que el servidor entiende. */
class ErrorMovil(val codigo: String, mensaje: String) : Exception(mensaje)
