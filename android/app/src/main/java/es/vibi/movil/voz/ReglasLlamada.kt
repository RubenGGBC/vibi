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
