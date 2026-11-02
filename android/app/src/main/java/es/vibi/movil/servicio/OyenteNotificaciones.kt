package es.vibi.movil.servicio

import android.service.notification.NotificationListenerService

/** Da acceso a las notificaciones y, con él, a las sesiones de música de otras apps. */
class OyenteNotificaciones : NotificationListenerService() {
    override fun onListenerConnected() {
        instancia = this
    }

    override fun onListenerDisconnected() {
        instancia = null
    }

    companion object {
        @Volatile
        var instancia: OyenteNotificaciones? = null
            private set
    }
}
