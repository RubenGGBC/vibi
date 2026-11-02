package es.vibi.movil.voz

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFocusRequest
import android.media.AudioManager
import es.vibi.movil.ajustes.Microfono

/**
 * Por dónde entra y sale el audio durante una llamada, y volver a dejarlo como estaba.
 *
 * Con el micro de los cascos, Bluetooth clásico pasa a perfil de llamada y la música
 * se queda en calidad de teléfono. Con el del móvil, los cascos siguen en estéreo y la
 * música solo baja de volumen mientras Vibi habla.
 */
class RutaAudio(contexto: Context) {
    private val audio = contexto.getSystemService(AudioManager::class.java)
    private var modoAnterior = AudioManager.MODE_NORMAL
    private var foco: AudioFocusRequest? = null

    val atributos: (Microfono) -> AudioAttributes = { mic ->
        AudioAttributes.Builder()
            .setUsage(
                if (mic == Microfono.CASCOS) AudioAttributes.USAGE_VOICE_COMMUNICATION
                else AudioAttributes.USAGE_MEDIA,
            )
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
    }

    fun aplicar(mic: Microfono) {
        modoAnterior = audio.mode
        val pedido = AudioFocusRequest.Builder(
            if (mic == Microfono.CASCOS) AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
            else AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK,
        ).setAudioAttributes(atributos(mic)).build()
        foco = pedido
        audio.requestAudioFocus(pedido)
        if (mic == Microfono.CASCOS) {
            audio.mode = AudioManager.MODE_IN_COMMUNICATION
            audio.availableCommunicationDevices
                .firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
                ?.let { audio.setCommunicationDevice(it) }
        }
    }

    /** Se llama siempre al colgar, también tras un error: la música debe volver sola. */
    fun restaurar() {
        audio.clearCommunicationDevice()
        audio.mode = modoAnterior
        foco?.let { audio.abandonAudioFocusRequest(it) }
        foco = null
    }
}
