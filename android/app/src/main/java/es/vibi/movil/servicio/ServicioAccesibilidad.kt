package es.vibi.movil.servicio

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent

/** La mano con la que Vibi toca otras apps. Solo actúa cuando llega una orden. */
class ServicioAccesibilidad : AccessibilityService() {
    override fun onServiceConnected() {
        instancia = this
    }

    override fun onAccessibilityEvent(evento: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        instancia = null
        super.onDestroy()
    }

    companion object {
        @Volatile
        var instancia: ServicioAccesibilidad? = null
            private set
    }
}
