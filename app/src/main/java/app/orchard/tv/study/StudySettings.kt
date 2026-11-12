package app.orchard.tv.study

import android.content.Context
import androidx.core.content.edit

/**
 * Settings for the optional Study Guard: a quiz every [INTERVAL_MIN] minutes of watching.
 *
 * Kept apart from Kids and Elders mode: this is an independent watch limit. Configured over ADB
 * while the feature is young (see ConfigReceiver), so that no new TV settings page is needed yet.
 */
object StudySettings {
    private const val PREFS = "study_guard"
    private const val KEY_ENABLED = "enabled"
    private const val KEY_URL = "url"
    private const val KEY_TOKEN = "token"
    private const val KEY_INTERVAL = "interval_min"
    private const val KEY_WATCH_MS = "watch_ms"
    private const val KEY_MIMO_KEY = "mimo_key"
    private const val KEY_MIMO_BASE = "mimo_base"
    private const val KEY_MIMO_ASR_MODEL = "mimo_asr_model"
    private const val KEY_MIMO_TTS_MODEL = "mimo_tts_model"
    private const val KEY_MIMO_VOICE = "mimo_voice"

    /** No server address is assumed; set one before enabling. */
    const val DEFAULT_URL = "http://saboop.local:8900"
    const val DEFAULT_INTERVAL_MIN = 6
    const val DEFAULT_MIMO_BASE = "https://api.xiaomimimo.com/v1"
    const val DEFAULT_MIMO_ASR_MODEL = "mimo-v2.5-asr"
    const val DEFAULT_MIMO_TTS_MODEL = "mimo-v2.5-tts"
    const val DEFAULT_MIMO_VOICE = "mimo_default"

    private var started = false
    private lateinit var app: Context

    fun init(context: Context) {
        if (started) return
        started = true
        app = context.applicationContext
    }

    private fun prefs() = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    var enabled: Boolean
        get() = prefs().getBoolean(KEY_ENABLED, false)
        set(value) = prefs().edit { putBoolean(KEY_ENABLED, value) }

    var baseUrl: String
        get() = prefs().getString(KEY_URL, DEFAULT_URL).orEmpty().trimEnd('/')
        set(value) = prefs().edit { putString(KEY_URL, value.trim()) }

    var deviceToken: String
        get() = prefs().getString(KEY_TOKEN, "").orEmpty()
        set(value) = prefs().edit { putString(KEY_TOKEN, value.trim()) }

    var intervalMinutes: Int
        get() = prefs().getInt(KEY_INTERVAL, DEFAULT_INTERVAL_MIN).coerceIn(1, 120)
        set(value) = prefs().edit { putInt(KEY_INTERVAL, value.coerceIn(1, 120)) }

    var watchMs: Long
        get() = prefs().getLong(KEY_WATCH_MS, 0L)
        set(value) = prefs().edit { putLong(KEY_WATCH_MS, value.coerceAtLeast(0L)) }

    /** MiMo cloud ASR/TTS are used when this is set; otherwise ASR falls back to NAS and TTS to Android. */
    var mimoApiKey: String
        get() = prefs().getString(KEY_MIMO_KEY, "").orEmpty()
        set(value) = prefs().edit { putString(KEY_MIMO_KEY, value.trim()) }

    var mimoBaseUrl: String
        get() = prefs().getString(KEY_MIMO_BASE, DEFAULT_MIMO_BASE).orEmpty().trimEnd('/')
        set(value) = prefs().edit { putString(KEY_MIMO_BASE, value.trim().trimEnd('/')) }

    var mimoAsrModel: String
        get() = prefs().getString(KEY_MIMO_ASR_MODEL, DEFAULT_MIMO_ASR_MODEL).orEmpty()
        set(value) = prefs().edit { putString(KEY_MIMO_ASR_MODEL, value.trim()) }

    var mimoTtsModel: String
        get() = prefs().getString(KEY_MIMO_TTS_MODEL, DEFAULT_MIMO_TTS_MODEL).orEmpty()
        set(value) = prefs().edit { putString(KEY_MIMO_TTS_MODEL, value.trim()) }

    var mimoVoice: String
        get() = prefs().getString(KEY_MIMO_VOICE, DEFAULT_MIMO_VOICE).orEmpty()
        set(value) = prefs().edit { putString(KEY_MIMO_VOICE, value.trim()) }

    val mimoConfigured: Boolean get() = mimoApiKey.isNotBlank()

    val intervalMs: Long get() = intervalMinutes * 60_000L

    fun resetWatch() {
        watchMs = 0L
    }

    fun addWatch(deltaMs: Long) {
        if (deltaMs > 0) watchMs += deltaMs
    }

    fun diagnostic(): String =
        "Study enabled=$enabled url=$baseUrl interval=${intervalMinutes}m watch=${watchMs / 1000}s mimo=${if (mimoConfigured) "on" else "off"}"
}
