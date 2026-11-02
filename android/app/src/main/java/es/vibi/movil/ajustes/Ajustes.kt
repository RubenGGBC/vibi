package es.vibi.movil.ajustes

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

enum class Microfono { MOVIL, CASCOS }

/** Lo que la app recuerda. El token de nodo va cifrado; la contraseña nunca se guarda. */
class Ajustes(contexto: Context) {
    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        contexto,
        "vibi_movil",
        MasterKey.Builder(contexto).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var baseUrl: String
        get() = prefs.getString("base_url", "") ?: ""
        set(valor) = prefs.edit { putString("base_url", valor.trimEnd('/')) }

    var token: String
        get() = prefs.getString("token", "") ?: ""
        set(valor) = prefs.edit { putString("token", valor) }

    var paqueteMusica: String
        get() = prefs.getString("paquete_musica", "") ?: ""
        set(valor) = prefs.edit { putString("paquete_musica", valor) }

    var micConversacion: Microfono
        get() = Microfono.valueOf(prefs.getString("mic_conversacion", null) ?: Microfono.CASCOS.name)
        set(valor) = prefs.edit { putString("mic_conversacion", valor.name) }

    var micEscucha: Microfono
        get() = Microfono.valueOf(prefs.getString("mic_escucha", null) ?: Microfono.MOVIL.name)
        set(valor) = prefs.edit { putString("mic_escucha", valor.name) }

    var silencioMs: Long
        get() = prefs.getLong("silencio_ms", 10_000)
        set(valor) = prefs.edit { putLong("silencio_ms", valor) }

    var palabraActiva: Boolean
        get() = prefs.getBoolean("palabra_activa", false)
        set(valor) = prefs.edit { putBoolean("palabra_activa", valor) }

    var botonActivo: Boolean
        get() = prefs.getBoolean("boton_activo", false)
        set(valor) = prefs.edit { putBoolean("boton_activo", valor) }

    val registrado: Boolean get() = baseUrl.isNotEmpty() && token.isNotEmpty()
}
