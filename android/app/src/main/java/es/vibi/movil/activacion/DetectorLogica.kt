package es.vibi.movil.activacion

import es.vibi.movil.capacidades.normalizar

/** Las reglas del detector de escritorio (`wake_listener.py`), con el alias «bibi». */
object DetectorLogica {
    /** Gramática de la primera etapa: Vosk no tiene «vibi», pero sí «bibi». */
    const val GRAMATICA = """["bibi", "[unk]"]"""

    private const val CONFIANZA_MINIMA = 0.8
    private const val ESPERA_ENTRE_DESPERTARES_MS = 3_000L
    private val FORMAS_CONFIRMADAS = setOf("bibi", "vibi", "vivi")

    /** Primera etapa: ¿dijo la palabra, y con qué seguridad? */
    fun candidato(palabra: String, confianza: Double): Boolean =
        normalizar(palabra) == "bibi" && confianza >= CONFIANZA_MINIMA

    /**
     * Segunda etapa, con el vocabulario completo. El modelo responde «manzana» o «mora»
     * a lo que la gramática restringida daba por «bibi». Basta con que aparezca una
     * forma exacta: «vivo» no cuenta.
     */
    fun confirmado(texto: String): Boolean =
        normalizar(texto).split(Regex("\\s+")).any { it in FORMAS_CONFIRMADAS }

    fun puedeDespertar(enLlamada: Boolean, ahora: Long, ultimoDespertar: Long): Boolean =
        !enLlamada && ahora - ultimoDespertar >= ESPERA_ENTRE_DESPERTARES_MS
}
