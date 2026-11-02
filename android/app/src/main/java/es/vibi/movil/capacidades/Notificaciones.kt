package es.vibi.movil.capacidades

import android.app.KeyguardManager
import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.service.notification.StatusBarNotification
import es.vibi.movil.nodo.Capacidad
import es.vibi.movil.nodo.ErrorMovil
import es.vibi.movil.servicio.OyenteNotificaciones
import org.json.JSONArray
import org.json.JSONObject

private fun oyente(): OyenteNotificaciones =
    OyenteNotificaciones.instancia
        ?: throw ErrorMovil("sin_permiso", "Falta conceder a Vibi el acceso a notificaciones.")

private fun buscar(id: String): StatusBarNotification =
    oyente().activeNotifications.orEmpty().firstOrNull { it.key == id }
        ?: throw ErrorMovil("no_encontrada", "Esa notificación ya no está.")

private fun acciones(notificacion: StatusBarNotification): List<Notification.Action> =
    notificacion.notification.actions.orEmpty().toList()

private fun comprobarDesbloqueo(contexto: Context, accion: Notification.Action) {
    val bloqueado = contexto.getSystemService(KeyguardManager::class.java).isKeyguardLocked
    if (accion.isAuthenticationRequired && bloqueado) {
        throw ErrorMovil("requiere_desbloqueo", "Para eso hay que desbloquear el móvil.")
    }
}

private fun enviar(contexto: Context, accion: Notification.Action, relleno: Intent? = null) {
    try {
        accion.actionIntent.send(contexto, 0, relleno)
    } catch (error: PendingIntent.CanceledException) {
        throw ErrorMovil("no_encontrada", "Esa notificación ya no está.")
    }
}

class CapacidadListarNotificaciones(private val contexto: Context) : Capacidad {
    override val nombre = "movil.notificaciones.listar"

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        val infos = oyente().activeNotifications.orEmpty().map(::aInfo)
        val filtradas = filtrarNotificaciones(
            infos,
            args.optString("app").ifEmpty { null },
            args.optInt("limite", 10),
            contexto.packageName,
        )
        val salida = JSONArray()
        filtradas.forEach { salida.put(aJson(it)) }
        return JSONObject().put("notificaciones", salida)
    }

    private fun aInfo(sbn: StatusBarNotification): NotifInfo {
        val extras = sbn.notification.extras
        val app = runCatching {
            val paquetes = contexto.packageManager
            paquetes.getApplicationLabel(paquetes.getApplicationInfo(sbn.packageName, 0)).toString()
        }.getOrDefault(sbn.packageName)
        return NotifInfo(
            id = sbn.key,
            paquete = sbn.packageName,
            app = app,
            titulo = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty(),
            texto = (
                extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
                    ?: extras.getCharSequence(Notification.EXTRA_TEXT)
                )?.toString().orEmpty(),
            hora = sbn.postTime,
            botones = acciones(sbn).map { it.title?.toString().orEmpty() },
            enCurso = sbn.isOngoing,
        )
    }

    private fun aJson(info: NotifInfo): JSONObject {
        val sbn = buscar(info.id)
        return JSONObject()
            .put("id", info.id)
            .put("app", info.app)
            .put("titulo", info.titulo)
            .put("texto", info.texto)
            .put("hora", info.hora)
            .put("botones", JSONArray(info.botones))
            .put("admite_respuesta", acciones(sbn).any { !it.remoteInputs.isNullOrEmpty() })
    }
}

class CapacidadDescartarNotificacion(private val contexto: Context) : Capacidad {
    override val nombre = "movil.notificaciones.descartar"

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        val id = args.optString("id")
        if (id.isNotEmpty()) {
            oyente().cancelNotification(buscar(id).key)
            return JSONObject().put("descartadas", 1)
        }
        val app = normalizar(args.optString("app"))
        if (app.isEmpty()) throw ErrorMovil("sin_objetivo", "Dime qué notificación descarto.")
        val paquetes = contexto.packageManager
        val coincidentes = oyente().activeNotifications.orEmpty().filter { sbn ->
            val nombre = runCatching {
                paquetes.getApplicationLabel(paquetes.getApplicationInfo(sbn.packageName, 0)).toString()
            }.getOrDefault(sbn.packageName)
            !sbn.isOngoing && normalizar(nombre).contains(app)
        }
        if (coincidentes.isEmpty()) throw ErrorMovil("no_encontrada", "No hay notificaciones de esa app.")
        coincidentes.forEach { oyente().cancelNotification(it.key) }
        return JSONObject().put("descartadas", coincidentes.size)
    }
}

class CapacidadPulsarNotificacion(private val contexto: Context) : Capacidad {
    override val nombre = "movil.notificaciones.pulsar"

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        val lista = acciones(buscar(args.optString("id")))
        val indice = indiceBoton(lista.map { it.title?.toString().orEmpty() }, args.optString("boton"))
        val accion = lista[indice]
        comprobarDesbloqueo(contexto, accion)
        enviar(contexto, accion)
        return JSONObject().put("pulsado", accion.title?.toString().orEmpty())
    }
}

class CapacidadResponderNotificacion(private val contexto: Context) : Capacidad {
    override val nombre = "movil.notificaciones.responder"

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        val texto = args.optString("texto")
        if (texto.isBlank()) throw ErrorMovil("sin_texto", "Dime qué respondo.")
        val lista = acciones(buscar(args.optString("id")))
        val accion = lista[indiceRespuesta(lista.map { !it.remoteInputs.isNullOrEmpty() })]
        comprobarDesbloqueo(contexto, accion)
        val entradas = accion.remoteInputs
        val relleno = Intent()
        val resultados = Bundle().apply { entradas.forEach { putCharSequence(it.resultKey, texto) } }
        RemoteInput.addResultsToIntent(entradas, relleno, resultados)
        enviar(contexto, accion, relleno)
        return JSONObject().put("respondido", true)
    }
}
