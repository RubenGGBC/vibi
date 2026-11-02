package es.vibi.movil.capacidades

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.accessibility.AccessibilityNodeInfo
import es.vibi.movil.nodo.Capacidad
import es.vibi.movil.nodo.ErrorMovil
import es.vibi.movil.servicio.ServicioAccesibilidad
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONArray
import org.json.JSONObject
import kotlin.coroutines.resume

private const val MAX_RECORRIDO = 2_000
private const val DESLIZAR_MS = 300L

private fun exigirDesbloqueado(contexto: Context) {
    if (contexto.getSystemService(KeyguardManager::class.java).isKeyguardLocked) {
        throw ErrorMovil("bloqueado", "El móvil está bloqueado: desbloquéalo para que pueda usar otras apps.")
    }
}

private fun servicio(): ServicioAccesibilidad =
    ServicioAccesibilidad.instancia
        ?: throw ErrorMovil("sin_accesibilidad", "Falta activar la accesibilidad de Vibi.")

class CapacidadLeerPantalla(
    private val contexto: Context,
    private val referencias: ReferenciasPantalla<AccessibilityNodeInfo>,
) : Capacidad {
    override val nombre = "movil.pantalla.leer"

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        exigirDesbloqueado(contexto)
        val raiz = servicio().rootInActiveWindow
            ?: throw ErrorMovil("sin_pantalla", "No puedo leer esta pantalla.")
        val nodos = mutableListOf<Pair<NodoInfo, AccessibilityNodeInfo>>()
        recorrer(raiz, nodos)
        val salida = JSONArray()
        referencias.nuevaLectura(nodos).forEach { nodo ->
            salida.put(
                JSONObject().put("ref", nodo.ref).put("rol", nodo.rol).put("texto", nodo.texto)
                    .put("clicable", nodo.clicable).put("editable", nodo.editable)
                    .put("desplazable", nodo.desplazable),
            )
        }
        return JSONObject().put("app", raiz.packageName?.toString().orEmpty()).put("nodos", salida)
    }

    private fun recorrer(
        nodo: AccessibilityNodeInfo,
        salida: MutableList<Pair<NodoInfo, AccessibilityNodeInfo>>,
    ) {
        if (salida.size >= MAX_RECORRIDO) return
        if (nodo.isVisibleToUser) {
            val texto = nodo.text?.toString() ?: nodo.contentDescription?.toString() ?: ""
            salida.add(
                NodoInfo(
                    nodo.className?.toString().orEmpty(),
                    texto,
                    nodo.isClickable,
                    nodo.isEditable,
                    nodo.isScrollable,
                ) to nodo,
            )
        }
        for (indice in 0 until nodo.childCount) {
            nodo.getChild(indice)?.let { recorrer(it, salida) }
        }
    }
}

class CapacidadActuarPantalla(
    private val contexto: Context,
    private val referencias: ReferenciasPantalla<AccessibilityNodeInfo>,
) : Capacidad {
    override val nombre = "movil.pantalla.actuar"

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        exigirDesbloqueado(contexto)
        val accion = args.optString("accion")
        val hecho = when (accion) {
            "atras" -> servicio().performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
            "inicio" -> servicio().performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME)
            "recientes" -> servicio().performGlobalAction(AccessibilityService.GLOBAL_ACTION_RECENTS)
            "tocar" -> tocar(objetivo(args))
            "escribir" -> escribir(objetivo(args), args.optString("texto"))
            "deslizar" -> deslizar(args.optString("direccion", "abajo"))
            else -> throw ErrorMovil("accion_desconocida", "No sé hacer «$accion» en la pantalla.")
        }
        if (!hecho) throw ErrorMovil("no_hecho", "No he podido hacer «$accion» en la pantalla.")
        return JSONObject().put("hecho", accion)
    }

    private fun objetivo(args: JSONObject): AccessibilityNodeInfo {
        val ref = args.optString("objetivo").ifEmpty { args.optString("ref") }
        if (ref.isEmpty()) throw ErrorMovil("sin_objetivo", "Falta decir sobre qué elemento actuar.")
        return referencias.resolver(ref)
    }

    /** Muchos textos no son pulsables, pero sí lo es el contenedor que los envuelve. */
    private fun tocar(nodo: AccessibilityNodeInfo): Boolean {
        var actual: AccessibilityNodeInfo? = nodo
        while (actual != null) {
            if (actual.isClickable) return actual.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            actual = actual.parent
        }
        return false
    }

    private fun escribir(nodo: AccessibilityNodeInfo, texto: String): Boolean {
        val valores = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, texto)
        }
        return nodo.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, valores)
    }

    private suspend fun deslizar(direccion: String): Boolean {
        val metricas = contexto.resources.displayMetrics
        val ancho = metricas.widthPixels.toFloat()
        val alto = metricas.heightPixels.toFloat()
        val centroX = ancho / 2
        val centroY = alto / 2
        val trazo = Path()
        when (direccion) {
            "abajo" -> { trazo.moveTo(centroX, alto * 0.75f); trazo.lineTo(centroX, alto * 0.25f) }
            "arriba" -> { trazo.moveTo(centroX, alto * 0.25f); trazo.lineTo(centroX, alto * 0.75f) }
            "izquierda" -> { trazo.moveTo(ancho * 0.8f, centroY); trazo.lineTo(ancho * 0.2f, centroY) }
            "derecha" -> { trazo.moveTo(ancho * 0.2f, centroY); trazo.lineTo(ancho * 0.8f, centroY) }
            else -> throw ErrorMovil("direccion_desconocida", "No sé deslizar hacia «$direccion».")
        }
        val gesto = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(trazo, 0, DESLIZAR_MS))
            .build()
        return suspendCancellableCoroutine { continuacion ->
            val lanzado = servicio().dispatchGesture(
                gesto,
                object : AccessibilityService.GestureResultCallback() {
                    override fun onCompleted(descripcion: GestureDescription?) {
                        continuacion.resume(true)
                    }

                    override fun onCancelled(descripcion: GestureDescription?) {
                        continuacion.resume(false)
                    }
                },
                null,
            )
            if (!lanzado) continuacion.resume(false)
        }
    }
}

class CapacidadAbrirApp(private val contexto: Context) : Capacidad {
    override val nombre = "movil.apps.abrir"

    override suspend fun ejecutar(args: JSONObject): JSONObject {
        val destino = args.optString("destino").trim()
        if (destino.isEmpty()) throw ErrorMovil("sin_destino", "Dime qué abro.")
        exigirDesbloqueado(contexto)
        if (!Settings.canDrawOverlays(contexto)) {
            throw ErrorMovil("sin_permiso", "Falta conceder a Vibi «mostrar sobre otras apps».")
        }
        val intent: Intent
        val abierta: String
        if (esEnlace(destino)) {
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(destino))
            abierta = destino
        } else {
            val app = resolverApp(instaladas(), destino)
            intent = contexto.packageManager.getLaunchIntentForPackage(app.paquete)
                ?: throw ErrorMovil("no_encontrada", "No puedo abrir ${app.nombre}.")
            abierta = app.nombre
        }
        try {
            contexto.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (error: Exception) {
            throw ErrorMovil("no_abre", "No he podido abrir $abierta.")
        }
        return JSONObject().put("abierta", abierta)
    }

    private fun instaladas(): List<AppInfo> {
        val paquetes = contexto.packageManager
        val lanzables = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return paquetes.queryIntentActivities(lanzables, 0).map {
            AppInfo(it.loadLabel(paquetes).toString(), it.activityInfo.packageName)
        }.distinctBy { it.paquete }
    }
}
