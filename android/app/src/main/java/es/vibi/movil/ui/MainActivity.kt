package es.vibi.movil.ui

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import es.vibi.movil.ajustes.Ajustes
import es.vibi.movil.ajustes.Microfono
import es.vibi.movil.servicio.OyenteNotificaciones
import es.vibi.movil.servicio.ServicioVibi
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import kotlin.concurrent.thread

/** Ajustes, permisos y medidas. Es una versión de prueba: lo mínimo que hace falta. */
class MainActivity : Activity() {
    private lateinit var ajustes: Ajustes
    private lateinit var lista: LinearLayout

    override fun onCreate(guardado: Bundle?) {
        super.onCreate(guardado)
        ajustes = Ajustes(this)
        lista = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 96, 48, 48)
        }
        setContentView(ScrollView(this).apply { addView(lista) })
    }

    override fun onResume() {
        super.onResume()
        pintar()
    }

    private fun pintar() {
        lista.removeAllViews()
        if (!ajustes.registrado) pintarRegistro() else pintarPanel()
    }

    private fun titulo(texto: String) = lista.addView(
        TextView(this).apply {
            text = texto
            textSize = 20f
            setPadding(0, 32, 0, 12)
        },
    )

    private fun boton(texto: String, alPulsar: () -> Unit) = lista.addView(
        Button(this).apply {
            text = texto
            isAllCaps = false
            setOnClickListener { alPulsar() }
        },
    )

    private fun campo(pista: String, tipo: Int, inicial: String = "") = EditText(this).apply {
        hint = pista
        inputType = tipo
        setText(inicial)
        lista.addView(this)
    }

    private fun pintarRegistro() {
        titulo("Conectar con tu Vibi")
        val url = campo("https://tu-pc.tu-tailnet.ts.net", InputType.TYPE_TEXT_VARIATION_URI)
        val usuario = campo("Usuario", InputType.TYPE_CLASS_TEXT)
        val clave = campo(
            "Contraseña",
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD,
        )
        boton("Conectar") {
            registrar(url.text.toString().trim(), usuario.text.toString().trim(), clave.text.toString())
        }
    }

    private fun registrar(url: String, usuario: String, clave: String) {
        thread {
            val resultado = runCatching {
                val cuerpo = JSONObject()
                    .put("nombre", usuario)
                    .put("contraseña", clave)
                    .put("nodo", Build.MODEL)
                    .put("plataforma", "Android ${Build.VERSION.RELEASE}")
                    .toString()
                    .toRequestBody("application/json".toMediaType())
                val peticion = Request.Builder().url(url.trimEnd('/') + "/api/auth/nodos").post(cuerpo).build()
                OkHttpClient().newCall(peticion).execute().use { respuesta ->
                    check(respuesta.isSuccessful) { "El servidor respondió ${respuesta.code}" }
                    JSONObject(respuesta.body!!.string()).getString("token")
                }
            }
            runOnUiThread {
                resultado.onSuccess {
                    ajustes.baseUrl = url
                    ajustes.token = it
                    pintar()
                }.onFailure {
                    Toast.makeText(this, it.message ?: "No he podido conectar", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun pintarPanel() {
        titulo("Vibi")
        lista.addView(
            TextView(this).apply {
                text = "${ServicioVibi.estado.value} · " +
                    if (ServicioVibi.conectado.value) "conectada al servidor" else "sin conexión con el servidor"
            },
        )
        boton("Encender") {
            pedirPermisosBasicos()
            ServicioVibi.arrancar(this)
            lista.postDelayed({ pintar() }, 800)
        }
        boton("Hablar") {
            startForegroundService(
                Intent(this, ServicioVibi::class.java).setAction(ServicioVibi.ACCION_HABLAR),
            )
        }
        boton("Parar") {
            ServicioVibi.parar(this)
            lista.postDelayed({ pintar() }, 300)
        }

        titulo("Permisos")
        pintarPermisos()

        titulo("Micrófono")
        microfono("Para conversar, usar el de los cascos", ajustes.micConversacion) {
            ajustes.micConversacion = it
        }
        microfono("Para escuchar «Vibi», usar el de los cascos", ajustes.micEscucha) {
            ajustes.micEscucha = it
        }

        titulo("Activación")
        interruptor("Palabra «Vibi» (experimental)", ajustes.palabraActiva) { ajustes.palabraActiva = it }
        interruptor("Botón de los cascos", ajustes.botonActivo) { ajustes.botonActivo = it }

        titulo("Silencio antes de colgar (segundos)")
        val silencio = campo("10", InputType.TYPE_CLASS_NUMBER, (ajustes.silencioMs / 1000).toString())
        boton("Guardar silencio") {
            ajustes.silencioMs = (silencio.text.toString().toLongOrNull()?.coerceIn(3, 120) ?: 10) * 1000
        }

        titulo("Medidas")
        boton("Copiar medidas") {
            val portapapeles = getSystemService(ClipboardManager::class.java)
            portapapeles.setPrimaryClip(ClipData.newPlainText("Medidas de Vibi", ServicioVibi.medidor.exportarJson()))
            Toast.makeText(this, "Medidas copiadas", Toast.LENGTH_SHORT).show()
        }

        titulo("Cuenta")
        boton("Olvidar este servidor") {
            ServicioVibi.parar(this)
            ajustes.token = ""
            pintar()
        }
    }

    private fun microfono(texto: String, actual: Microfono, guardar: (Microfono) -> Unit) =
        interruptor(texto, actual == Microfono.CASCOS) {
            guardar(if (it) Microfono.CASCOS else Microfono.MOVIL)
        }

    private fun interruptor(texto: String, activo: Boolean, guardar: (Boolean) -> Unit) = lista.addView(
        CheckBox(this).apply {
            text = texto
            isChecked = activo
            setOnCheckedChangeListener { _: View, valor: Boolean -> guardar(valor) }
        },
    )

    private fun pedirPermisosBasicos() {
        requestPermissions(
            arrayOf(
                Manifest.permission.RECORD_AUDIO,
                Manifest.permission.POST_NOTIFICATIONS,
                Manifest.permission.BLUETOOTH_CONNECT,
            ),
            1,
        )
    }

    private fun pintarPermisos() {
        val energia = getSystemService(PowerManager::class.java)
        permiso("Micrófono y notificaciones", tienePermisosBasicos()) { pedirPermisosBasicos() }
        permiso("Sin límite de batería (One UI)", energia.isIgnoringBatteryOptimizations(packageName)) {
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")),
            )
        }
        permiso("Acceso a notificaciones", accesoANotificaciones()) {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        permiso("Accesibilidad", accesibilidadActiva()) {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        permiso("Mostrar sobre otras apps", Settings.canDrawOverlays(this)) {
            startActivity(
                Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")),
            )
        }
        lista.addView(
            TextView(this).apply {
                text = "Si Android dice «ajuste restringido»: Ajustes › Aplicaciones › Vibi › ⋮ › " +
                    "Permitir ajustes restringidos. Si One UI bloquea la instalación, desactiva el " +
                    "Bloqueador automático."
                setPadding(0, 12, 0, 0)
            },
        )
    }

    private fun permiso(nombre: String, concedido: Boolean, pedir: () -> Unit) =
        boton((if (concedido) "✓ " else "Conceder: ") + nombre, pedir)

    private fun tienePermisosBasicos() =
        checkSelfPermission(Manifest.permission.RECORD_AUDIO) == android.content.pm.PackageManager.PERMISSION_GRANTED &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED

    private fun accesoANotificaciones(): Boolean {
        val habilitados = Settings.Secure.getString(contentResolver, "enabled_notification_listeners").orEmpty()
        return habilitados.contains(ComponentName(this, OyenteNotificaciones::class.java).flattenToString())
    }

    private fun accesibilidadActiva(): Boolean {
        val activos = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
        return activos.contains(packageName)
    }
}
