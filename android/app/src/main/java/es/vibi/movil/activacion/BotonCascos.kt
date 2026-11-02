package es.vibi.movil.activacion

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import es.vibi.movil.ajustes.Ajustes
import es.vibi.movil.servicio.ServicioVibi

/**
 * Lo que abren los cascos al pedir el asistente de voz (`VOICE_COMMAND`).
 *
 * Los botones multimedia van a la app de música, no a Vibi, así que esta es la vía que
 * pueden usar unos TWS genéricos con su pulsación larga. Android preguntará qué app usar.
 */
class BotonCascos : Activity() {
    override fun onCreate(guardado: Bundle?) {
        super.onCreate(guardado)
        if (Ajustes(this).botonActivo) {
            startForegroundService(
                Intent(this, ServicioVibi::class.java)
                    .setAction(ServicioVibi.ACCION_HABLAR)
                    .putExtra(ServicioVibi.EXTRA_ORIGEN, "boton_cascos"),
            )
        }
        finish()
    }
}
