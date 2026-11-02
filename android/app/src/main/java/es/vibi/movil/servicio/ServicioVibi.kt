package es.vibi.movil.servicio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import es.vibi.movil.activacion.PalabraVibi
import es.vibi.movil.ajustes.Ajustes
import es.vibi.movil.capacidades.Registro
import es.vibi.movil.medidas.Medidor
import es.vibi.movil.nodo.ClienteNodo
import es.vibi.movil.ui.MainActivity
import es.vibi.movil.voz.LlamadaVoz
import kotlinx.coroutines.flow.MutableStateFlow
import java.util.concurrent.atomic.AtomicInteger

/** Mantiene a Vibi viva: conexión con el servidor, escucha y llamada. */
class ServicioVibi : Service() {
    private lateinit var ajustes: Ajustes
    private var nodo: ClienteNodo? = null
    private var llamada: LlamadaVoz? = null
    private var candado: PowerManager.WakeLock? = null
    private var palabra: PalabraVibi? = null
    private val avisos = AtomicInteger(100)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ajustes = Ajustes(this)
        crearCanales()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACCION_PARAR -> {
                detener()
                return START_NOT_STICKY
            }
            ACCION_HABLAR -> {
                asegurarArranque()
                activar(intent.getStringExtra(EXTRA_ORIGEN) ?: "boton_notificacion")
            }
            else -> asegurarArranque()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        apagar()
        super.onDestroy()
    }

    private fun asegurarArranque() {
        startForeground(ID_FIJA, notificacion("En espera"), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        if (nodo != null || !ajustes.registrado) return
        candado = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "vibi:servicio")
            .apply { acquire() }
        llamada = LlamadaVoz(
            this,
            ajustes,
            medidor,
            onEstado = { actualizar(it) },
            onTerminada = { reanudarEscucha() },
        )
        nodo = ClienteNodo(
            baseUrl = ajustes.baseUrl,
            token = ajustes.token,
            capacidades = Registro.todas(this, ajustes, medidor),
            onNotificacion = { avisar(it) },
            onEstado = { conectado.value = it },
        ).also { it.conectar() }
        instancia = this
        arrancarActivadores()
    }

    /** Lo llaman el botón, el gesto de los cascos y la palabra. */
    fun activar(origen: String) {
        pausarEscucha()
        llamada?.iniciar(origen)
    }

    private fun arrancarActivadores() {
        if (!ajustes.palabraActiva) return
        palabra = PalabraVibi(
            this,
            ajustes,
            enLlamada = { llamada?.enCurso == true },
            onDespertar = { activar("palabra") },
            onEstado = { actualizar(it) },
        ).also { it.arrancar() }
    }

    /** El micrófono no se comparte: mientras se conversa, nadie más escucha. */
    private fun pausarEscucha() {
        palabra?.parar()
    }

    private fun reanudarEscucha() {
        palabra?.arrancar()
    }

    private fun apagarActivadores() {
        palabra?.parar()
        palabra = null
    }

    private fun apagar() {
        instancia = null
        apagarActivadores()
        llamada?.colgar()
        llamada = null
        nodo?.parar()
        nodo = null
        candado?.takeIf { it.isHeld }?.release()
        candado = null
    }

    private fun detener() {
        apagar()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun crearCanales() {
        val gestor = getSystemService(NotificationManager::class.java)
        gestor.createNotificationChannel(
            NotificationChannel(CANAL_FIJO, "Vibi en marcha", NotificationManager.IMPORTANCE_LOW),
        )
        gestor.createNotificationChannel(
            NotificationChannel(CANAL_AVISOS, "Avisos de Vibi", NotificationManager.IMPORTANCE_DEFAULT),
        )
    }

    private fun accion(accion: String, codigo: Int) = PendingIntent.getService(
        this,
        codigo,
        Intent(this, ServicioVibi::class.java).setAction(accion),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun notificacion(texto: String): Notification =
        Notification.Builder(this, CANAL_FIJO)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("Vibi")
            .setContentText(texto)
            .setOngoing(true)
            .setContentIntent(
                PendingIntent.getActivity(
                    this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
                ),
            )
            .addAction(Notification.Action.Builder(null, "Hablar", accion(ACCION_HABLAR, 1)).build())
            .addAction(Notification.Action.Builder(null, "Parar", accion(ACCION_PARAR, 2)).build())
            .build()

    private fun actualizar(texto: String) {
        estado.value = texto
        getSystemService(NotificationManager::class.java).notify(ID_FIJA, notificacion(texto))
    }

    private fun avisar(texto: String) {
        val aviso = Notification.Builder(this, CANAL_AVISOS)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Vibi")
            .setContentText(texto)
            .setStyle(Notification.BigTextStyle().bigText(texto))
            .build()
        getSystemService(NotificationManager::class.java).notify(avisos.incrementAndGet(), aviso)
    }

    companion object {
        const val ACCION_HABLAR = "es.vibi.movil.HABLAR"
        const val ACCION_PARAR = "es.vibi.movil.PARAR"
        const val EXTRA_ORIGEN = "origen"
        private const val CANAL_FIJO = "vibi_fijo"
        private const val CANAL_AVISOS = "vibi_avisos"
        private const val ID_FIJA = 1

        val medidor = Medidor { SystemClock.elapsedRealtime() }
        val estado = MutableStateFlow("Parada")
        val conectado = MutableStateFlow(false)

        @Volatile
        var instancia: ServicioVibi? = null
            private set

        fun arrancar(contexto: Context) {
            contexto.startForegroundService(Intent(contexto, ServicioVibi::class.java))
        }

        fun parar(contexto: Context) {
            contexto.startService(Intent(contexto, ServicioVibi::class.java).setAction(ACCION_PARAR))
        }
    }
}
