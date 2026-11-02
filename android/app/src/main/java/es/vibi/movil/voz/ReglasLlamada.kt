package es.vibi.movil.voz

object ReglasLlamada {
    /** Por encima de esto, lo que llega del servidor es Vibi hablando. */
    private const val UMBRAL_SALIDA = 0.012

    fun hayVoz(nivel: Double): Boolean = nivel > UMBRAL_SALIDA

    /** Se cuelga tras un silencio de verdad, nunca con alguien hablando o una orden en curso. */
    fun debeColgar(
        ahora: Long,
        ultimaVozVibi: Long,
        delegando: Boolean,
        usuarioHablando: Boolean,
        vibiHablando: Boolean,
        silencioMs: Long = 10_000,
    ): Boolean {
        if (delegando || usuarioHablando || vibiHablando) return false
        return ahora - ultimaVozVibi >= silencioMs
    }
}

/**
 * Lo que se enseña de la llamada. Un error se queda a la vista al colgar, porque es lo
 * único que explica lo ocurrido, y tras apagar nada vuelve a publicarse.
 */
class EstadoLlamada(private val publicarEn: (String) -> Unit) {
    private var hayError = false
    private var apagado = false

    @Synchronized
    fun publicar(texto: String) {
        if (apagado) return
        hayError = false
        publicarEn(texto)
    }

    @Synchronized
    fun error(texto: String) {
        if (apagado) return
        hayError = true
        publicarEn(texto)
    }

    @Synchronized
    fun terminar() {
        if (apagado || hayError) return
        publicarEn("En espera")
    }

    @Synchronized
    fun apagar() {
        apagado = true
    }
}

/** Varias herramientas pueden ir a la vez: una tarea lenta y un «siguiente canción». */
class HerramientasEnCurso {
    private var cuantas = 0

    val hay: Boolean
        @Synchronized get() = cuantas > 0

    @Synchronized
    fun empieza() {
        cuantas++
    }

    @Synchronized
    fun termina() {
        if (cuantas > 0) cuantas--
    }

    @Synchronized
    fun reiniciar() {
        cuantas = 0
    }
}

/** La música vuelve antes de hablar con el servidor, que puede no contestar. */
fun cerrarLlamada(liberar: () -> Unit, restaurar: () -> Unit, avisar: () -> Unit) {
    runCatching(liberar)
    runCatching(restaurar)
    runCatching(avisar)
}
