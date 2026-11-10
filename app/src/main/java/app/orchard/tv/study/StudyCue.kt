package app.orchard.tv.study

import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log

/** Immediate local earcons for the quiz. They never go through TTS or the network. */
object StudyCue {
    private const val TAG = "AerialStudy"
    private val main = Handler(Looper.getMainLooper())

    fun start() = beep(ToneGenerator.TONE_PROP_BEEP, 130, 75)

    fun end() = beep(ToneGenerator.TONE_PROP_ACK, 110, 65)

    private fun beep(tone: Int, durationMs: Int, volume: Int) {
        val stream = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            AudioManager.STREAM_ACCESSIBILITY
        } else {
            AudioManager.STREAM_NOTIFICATION
        }
        val generator = runCatching { ToneGenerator(stream, volume) }
            .onFailure { Log.w(TAG, "tone generator unavailable", it) }
            .getOrNull() ?: return
        runCatching { generator.startTone(tone, durationMs) }
        main.postDelayed({ runCatching { generator.release() } }, durationMs + 80L)
    }
}
