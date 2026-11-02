package es.vibi.movil.voz

import android.content.Context
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.SystemClock
import android.util.Log
import es.vibi.movil.R
import es.vibi.movil.ajustes.Ajustes
import es.vibi.movil.ajustes.Microfono
import es.vibi.movil.medidas.Medidor
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import org.webrtc.AudioTrack
import org.webrtc.DataChannel
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RTCStatsReport
import org.webrtc.RtpReceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.audio.JavaAudioDeviceModule
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicBoolean

private const val TAG = "VibiLlamada"
private const val SONDEO_MS = 1_500L
private const val NIVEL_MS = 250L
private const val ESPERA_ICE_MS = 500L
private const val PAUSA_SALIDA_MS = 700L

/** La conversación con la voz de Codex. Audio directo con OpenAI por WebRTC. */
class LlamadaVoz(
    private val contexto: Context,
    private val ajustes: Ajustes,
    private val medidor: Medidor,
    onEstado: (String) -> Unit = {},
    private val onError: (String) -> Unit = {},
    private val onTerminada: () -> Unit = {},
) {
    private val estado = EstadoLlamada(onEstado)
    private val herramientas = HerramientasEnCurso()
    private val alcance = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val activa = AtomicBoolean(false)
    private val ruta = RutaAudio(contexto)

    private var trabajo: Job? = null
    private var factoria: PeerConnectionFactory? = null
    private var modulo: JavaAudioDeviceModule? = null
    private var conexion: PeerConnection? = null
    private var api: ApiVoz? = null

    @Volatile private var abiertaEnServidor = false
    @Volatile private var sondeoTerminado = false
    @Volatile private var errorPendiente: String? = null
    @Volatile private var usuarioHablando = false
    @Volatile private var ultimaVozVibi = 0L
    @Volatile private var vibiHablando = false

    val enCurso: Boolean get() = activa.get()

    fun iniciar(origen: String) {
        if (!activa.compareAndSet(false, true)) return
        medidor.nuevaSesion(origen)
        sonarPing()
        medidor.marcar("ping")
        estado.publicar("Conectando…")
        trabajo = alcance.launch {
            try {
                conversar()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                Log.w(TAG, "La llamada ha fallado", error)
                fallar(error.message ?: "La llamada ha fallado")
            } finally {
                terminar()
            }
        }
    }

    fun colgar() {
        trabajo?.cancel()
    }

    /** Para siempre: el servicio se va y nada debe volver a publicar su estado. */
    fun apagar() {
        estado.apagar()
        colgar()
    }

    private fun fallar(mensaje: String) {
        errorPendiente = mensaje
        medidor.marcarError(mensaje)
        estado.error(mensaje)
    }

    private fun sonarPing() {
        runCatching {
            MediaPlayer.create(contexto, R.raw.ping)?.apply {
                setOnCompletionListener { it.release() }
                start()
            }
        }
    }

    private suspend fun conversar() {
        val mic = ajustes.micConversacion
        val cliente = ApiVoz(ajustes.baseUrl, ajustes.token)
        api = cliente
        ruta.aplicar(mic)
        val pc = crearConexion(mic)
        pc.createDataChannel("oai-events", DataChannel.Init()).registerObserver(CanalEventos { alEvento(it) })

        val oferta = crearOferta(pc)
        medidor.marcar("peticion")
        val respuesta = cliente.abrir(oferta)
        abiertaEnServidor = true
        medidor.marcar("sdp")
        ponerRemota(pc, respuesta.sdp)
        estado.publicar("Te escucho")
        ultimaVozVibi = SystemClock.elapsedRealtime()
        vigilar(pc, cliente, respuesta.conversationId)
    }

    private fun crearConexion(mic: Microfono): PeerConnection {
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(contexto).createInitializationOptions(),
        )
        val audio = JavaAudioDeviceModule.builder(contexto)
            .setAudioAttributes(ruta.atributos(mic))
            .setAudioSource(
                if (mic == Microfono.CASCOS) MediaRecorder.AudioSource.VOICE_COMMUNICATION
                else MediaRecorder.AudioSource.MIC,
            )
            .setUseHardwareAcousticEchoCanceler(true)
            .setUseHardwareNoiseSuppressor(true)
            .createAudioDeviceModule()
        modulo = audio
        val nueva = PeerConnectionFactory.builder().setAudioDeviceModule(audio).createPeerConnectionFactory()
        factoria = nueva
        val config = PeerConnection.RTCConfiguration(emptyList()).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }
        val pc = nueva.createPeerConnection(config, ObservadorConexion()) ?: error("No se pudo crear la conexión de audio")
        conexion = pc
        val restricciones = MediaConstraints()
        val fuente = nueva.createAudioSource(restricciones)
        val pista: AudioTrack = nueva.createAudioTrack("microfono", fuente)
        pc.addTrack(pista, listOf("vibi"))
        return pc
    }

    private suspend fun crearOferta(pc: PeerConnection): String {
        val creada = CompletableDeferred<SessionDescription>()
        pc.createOffer(object : ObservadorSdp() {
            override fun onCreateSuccess(descripcion: SessionDescription) {
                creada.complete(descripcion)
            }

            override fun onCreateFailure(error: String?) {
                creada.completeExceptionally(IllegalStateException(error))
            }
        }, MediaConstraints())
        val descripcion = creada.await()
        ponerLocal(pc, descripcion)
        // Sin esperar del todo: el navegador tampoco lo hace y cada milisegundo cuenta.
        withTimeoutOrNull(ESPERA_ICE_MS) {
            while (pc.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) delay(20)
        }
        return pc.localDescription.description
    }

    private suspend fun ponerLocal(pc: PeerConnection, descripcion: SessionDescription) {
        val hecho = CompletableDeferred<Unit>()
        pc.setLocalDescription(observadorPoner(hecho), descripcion)
        hecho.await()
    }

    private suspend fun ponerRemota(pc: PeerConnection, sdp: String) {
        val hecho = CompletableDeferred<Unit>()
        pc.setRemoteDescription(observadorPoner(hecho), SessionDescription(SessionDescription.Type.ANSWER, sdp))
        hecho.await()
    }

    private fun observadorPoner(hecho: CompletableDeferred<Unit>) = object : ObservadorSdp() {
        override fun onSetSuccess() {
            hecho.complete(Unit)
        }

        override fun onSetFailure(error: String?) {
            hecho.completeExceptionally(IllegalStateException(error))
        }
    }

    private suspend fun vigilar(pc: PeerConnection, cliente: ApiVoz, conversacion: String) {
        // Aparte: aunque el servidor tarde en contestar, la conexión y el silencio se siguen vigilando.
        sondeoTerminado = false
        val sondeo = alcance.launch {
            while (isActive) {
                if (!sondear(cliente, conversacion)) {
                    sondeoTerminado = true
                    return@launch
                }
                delay(SONDEO_MS)
            }
        }
        try {
            while (activa.get() && !sondeoTerminado) {
                val ahora = SystemClock.elapsedRealtime()
                medirSalida(pc)
                if (pc.connectionState() == PeerConnection.PeerConnectionState.FAILED) {
                    fallar("Se ha perdido la conexión de audio")
                    return
                }
                if (ReglasLlamada.debeColgar(
                        ahora, ultimaVozVibi, herramientas.hay, usuarioHablando, vibiHablando, ajustes.silencioMs,
                    )
                ) {
                    return
                }
                delay(NIVEL_MS)
            }
        } finally {
            sondeo.cancel()
        }
    }

    /** `false` si la llamada ya no sigue. Un sondeo perdido no corta: el servidor aguanta 30 s. */
    private fun sondear(cliente: ApiVoz, conversacion: String): Boolean {
        val respuesta = runCatching { cliente.eventos(conversacion) }.getOrNull() ?: return true
        for (evento in respuesta.eventos) {
            when (evento.optString("type")) {
                "vibi/request" -> {
                    herramientas.empieza()
                    medidor.marcar("herramienta")
                }
                "vibi/result" -> {
                    herramientas.termina()
                    medidor.marcar("resultado")
                    ultimaVozVibi = SystemClock.elapsedRealtime()
                }
                "vibi/cerrar" -> return false
                "error" -> {
                    fallar(evento.optString("message", "La voz de Codex ha fallado"))
                    return false
                }
            }
        }
        return respuesta.activa
    }

    private fun medirSalida(pc: PeerConnection) {
        pc.getStats { informe: RTCStatsReport ->
            val nivel = informe.statsMap.values
                .firstOrNull { it.type == "inbound-rtp" && it.members["kind"] == "audio" }
                ?.members?.get("audioLevel") as? Double ?: 0.0
            val ahora = SystemClock.elapsedRealtime()
            if (ReglasLlamada.hayVoz(nivel)) {
                medidor.marcar("primera_voz")
                ultimaVozVibi = ahora
                vibiHablando = true
            } else if (ahora - ultimaVozVibi > PAUSA_SALIDA_MS) {
                vibiHablando = false
            }
        }
    }

    private fun alEvento(mensaje: JSONObject) {
        val tipo = mensaje.optString("type")
        when {
            tipo.contains("speech_started") -> usuarioHablando = true
            tipo.contains("speech_stopped") -> {
                usuarioHablando = false
                medidor.marcarFinFrase()
                ultimaVozVibi = SystemClock.elapsedRealtime()
            }
        }
    }

    private fun terminar() {
        val colgarEnServidor = abiertaEnServidor
        val cliente = api
        abiertaEnServidor = false
        cerrarLlamada(
            liberar = {
                runCatching { conexion?.dispose() }
                runCatching { modulo?.release() }
                runCatching { factoria?.dispose() }
            },
            // Pase lo que pase, la música vuelve a como estaba.
            restaurar = { ruta.restaurar() },
            avisar = {
                if (colgarEnServidor) alcance.launch { runCatching { cliente?.colgar() } }
            },
        )
        conexion = null
        modulo = null
        factoria = null
        herramientas.reiniciar()
        usuarioHablando = false
        vibiHablando = false
        activa.set(false)
        estado.terminar()
        errorPendiente?.let(onError)
        errorPendiente = null
        onTerminada()
    }

    private inner class ObservadorConexion : PeerConnection.Observer {
        override fun onConnectionChange(nuevo: PeerConnection.PeerConnectionState) {
            if (nuevo == PeerConnection.PeerConnectionState.CONNECTED) medidor.marcar("webrtc")
        }

        override fun onSignalingChange(estado: PeerConnection.SignalingState) = Unit
        override fun onIceConnectionChange(estado: PeerConnection.IceConnectionState) = Unit
        override fun onIceConnectionReceivingChange(recibiendo: Boolean) = Unit
        override fun onIceGatheringChange(estado: PeerConnection.IceGatheringState) = Unit
        override fun onIceCandidate(candidato: IceCandidate) = Unit
        override fun onIceCandidatesRemoved(candidatos: Array<out IceCandidate>) = Unit
        override fun onAddStream(flujo: MediaStream) = Unit
        override fun onRemoveStream(flujo: MediaStream) = Unit
        override fun onDataChannel(canal: DataChannel) = Unit
        override fun onRenegotiationNeeded() = Unit
        override fun onAddTrack(receptor: RtpReceiver, flujos: Array<out MediaStream>) = Unit
    }

    private class CanalEventos(private val alMensaje: (JSONObject) -> Unit) : DataChannel.Observer {
        override fun onBufferedAmountChange(anterior: Long) = Unit
        override fun onStateChange() = Unit
        override fun onMessage(buffer: DataChannel.Buffer) {
            val bytes = ByteArray(buffer.data.remaining())
            buffer.data.get(bytes)
            runCatching { alMensaje(JSONObject(String(bytes, StandardCharsets.UTF_8))) }
        }
    }

    private open class ObservadorSdp : SdpObserver {
        override fun onCreateSuccess(descripcion: SessionDescription) = Unit
        override fun onSetSuccess() = Unit
        override fun onCreateFailure(error: String?) = Unit
        override fun onSetFailure(error: String?) = Unit
    }
}
