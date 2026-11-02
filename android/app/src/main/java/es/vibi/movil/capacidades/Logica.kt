package es.vibi.movil.capacidades

import es.vibi.movil.nodo.ErrorMovil
import java.text.Normalizer
import kotlin.math.roundToInt

private const val MAX_TEXTO = 500
private const val MAX_NODOS = 200

/** Por voz nadie pronuncia los acentos ni las mayúsculas de un nombre. */
fun normalizar(texto: String): String =
    Normalizer.normalize(texto, Normalizer.Form.NFD)
        .replace(Regex("\\p{M}+"), "")
        .lowercase()
        .trim()

// ---------- Música ----------

data class SesionInfo(val paquete: String, val sonando: Boolean)

fun elegirSesion(sesiones: List<SesionInfo>, guardada: String): SesionInfo =
    sesiones.firstOrNull { it.paquete == guardada }
        ?: sesiones.firstOrNull { it.sonando }
        ?: sesiones.firstOrNull()
        ?: throw ErrorMovil("sin_musica", "No hay ninguna app de música abierta.")

data class EstadoMusica(val titulo: String?, val sonando: Boolean)

/** Solo se confirma lo que se ve que ha ocurrido. */
fun efectoCumplido(accion: String, antes: EstadoMusica, despues: EstadoMusica): Boolean =
    when (accion) {
        "pausar" -> !despues.sonando
        "reanudar" -> despues.sonando
        "siguiente", "anterior" -> despues.titulo != antes.titulo
        else -> true
    }

fun cancionCambiada(tituloAnterior: String?, ahora: EstadoMusica?): Boolean =
    ahora != null && ahora.sonando && ahora.titulo != tituloAnterior

fun errorAlAbrir(bloqueado: Boolean): ErrorMovil =
    if (bloqueado) {
        ErrorMovil("bloqueado", "No he podido poner la canción con el móvil bloqueado: desbloquéalo.")
    } else {
        ErrorMovil("no_abre", "Tu app de música no ha empezado a sonar con esa canción.")
    }

fun indiceVolumen(porcentaje: Int, maximo: Int): Int =
    (porcentaje.coerceIn(0, 100) / 100.0 * maximo).roundToInt()

// ---------- Notificaciones ----------

data class NotifInfo(
    val id: String,
    val paquete: String,
    val app: String,
    val titulo: String,
    val texto: String,
    val hora: Long,
    val botones: List<String>,
    val enCurso: Boolean,
)

fun filtrarNotificaciones(
    lista: List<NotifInfo>,
    app: String?,
    limite: Int,
    paquetePropio: String,
): List<NotifInfo> {
    val buscada = app?.let(::normalizar)?.takeIf { it.isNotEmpty() }
    return lista.asSequence()
        .filter { !it.enCurso && it.paquete != paquetePropio }
        .filter { buscada == null || normalizar(it.app).contains(buscada) }
        .sortedByDescending { it.hora }
        .take(limite.coerceIn(1, 50))
        .map { it.copy(texto = recortar(it.texto)) }
        .toList()
}

private fun recortar(texto: String) =
    if (texto.length <= MAX_TEXTO) texto else texto.take(MAX_TEXTO) + "…"

fun indiceBoton(botones: List<String>, nombre: String): Int {
    val indice = botones.indexOfFirst { normalizar(it) == normalizar(nombre) }
    if (indice < 0) throw ErrorMovil("sin_boton", "Esa notificación no tiene el botón «$nombre».")
    return indice
}

fun indiceRespuesta(admitenRespuesta: List<Boolean>): Int {
    val indice = admitenRespuesta.indexOf(true)
    if (indice < 0) throw ErrorMovil("sin_respuesta", "Esa notificación no permite responder.")
    return indice
}

// ---------- Pantalla ----------

data class NodoInfo(
    val rol: String,
    val texto: String,
    val clicable: Boolean,
    val editable: Boolean,
    val desplazable: Boolean,
)

data class NodoLeido(
    val ref: String,
    val rol: String,
    val texto: String,
    val clicable: Boolean,
    val editable: Boolean,
    val desplazable: Boolean,
)

/** Cada lectura invalida las anteriores: una referencia vieja apuntaría a otra cosa. */
class ReferenciasPantalla<T> {
    private var generacion = 0
    private var actuales: List<T> = emptyList()

    @Synchronized
    fun nuevaLectura(nodos: List<Pair<NodoInfo, T>>): List<NodoLeido> {
        generacion++
        val utiles = nodos.filter { (nodo, _) ->
            nodo.texto.isNotBlank() || nodo.clicable || nodo.editable || nodo.desplazable
        }.take(MAX_NODOS)
        actuales = utiles.map { it.second }
        return utiles.mapIndexed { indice, (nodo, _) ->
            NodoLeido(
                "$generacion:$indice",
                nodo.rol.substringAfterLast('.'),
                recortar(nodo.texto),
                nodo.clicable,
                nodo.editable,
                nodo.desplazable,
            )
        }
    }

    @Synchronized
    fun resolver(ref: String): T {
        val partes = ref.split(':')
        val indice = partes.getOrNull(1)?.toIntOrNull()
        if (partes.size != 2 || partes[0] != generacion.toString() || indice == null) {
            throw ErrorMovil("ref_caducada", "La pantalla ha cambiado: vuelve a leerla.")
        }
        return actuales.getOrNull(indice)
            ?: throw ErrorMovil("ref_caducada", "La pantalla ha cambiado: vuelve a leerla.")
    }
}

// ---------- Apps ----------

data class AppInfo(val nombre: String, val paquete: String)

fun esEnlace(destino: String): Boolean =
    destino.startsWith("http://", ignoreCase = true) || destino.startsWith("https://", ignoreCase = true)

fun resolverApp(apps: List<AppInfo>, consulta: String): AppInfo {
    val buscada = normalizar(consulta)
    apps.firstOrNull { normalizar(it.nombre) == buscada }?.let { return it }
    val parciales = apps.filter { normalizar(it.nombre).contains(buscada) }
    return when (parciales.size) {
        0 -> throw ErrorMovil("no_encontrada", "No encuentro la app «$consulta».")
        1 -> parciales.single()
        else -> throw ErrorMovil(
            "ambiguo",
            "Hay varias apps: " + parciales.take(6).joinToString(", ") { it.nombre },
        )
    }
}
