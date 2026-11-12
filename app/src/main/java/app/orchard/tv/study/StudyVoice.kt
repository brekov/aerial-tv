package app.orchard.tv.study

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import java.io.File
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Short spoken feedback for the quiz. Prefers MiMo-V2.5-TTS when a key is configured on the TV;
 * otherwise uses the TV's local Android TTS. Never calls the NAS.
 */
object StudyVoice {
    private const val TAG = "AerialStudy"
    private val main = Handler(Looper.getMainLooper())
    private var generation = 0
    private var player: MediaPlayer? = null
    private var tts: TextToSpeech? = null

    fun speak(context: Context, text: String, onDone: () -> Unit) {
        val app = context.applicationContext
        main.post {
            val gen = ++generation
            releaseCurrent()
            if (StudySettings.mimoConfigured) {
                val cached = cachedFile(app, text)
                if (cached != null && cached.length() > 0) {
                    playFile(app, gen, text, cached, onDone, deleteOnDone = false)
                    return@post
                }
                Thread({
                    val audio = runCatching { MimoClient.synthesize(text) }
                        .onFailure { Log.w(TAG, "MiMo TTS failed; using Android TTS", it) }
                        .getOrNull()
                    main.post {
                        if (gen != generation) return@post
                        if (audio != null && audio.isNotEmpty()) {
                            val target = cachedFile(app, text)
                            if (target != null && runCatching { target.writeBytes(audio) }.isSuccess) {
                                playFile(app, gen, text, target, onDone, deleteOnDone = false)
                            } else {
                                playWav(app, gen, text, audio, onDone)
                            }
                        } else {
                            androidSpeak(app, gen, text, onDone)
                        }
                    }
                }, "study-tts").apply { isDaemon = true }.start()
            } else {
                androidSpeak(app, gen, text, onDone)
            }
        }
    }

    /** Speak the word, then spell its letters; used by repeat-learning. */
    fun speakSpelling(context: Context, word: String, letters: List<String>, onDone: () -> Unit) {
        val app = context.applicationContext
        main.post {
            val gen = ++generation
            releaseCurrent()
            val text = word + ", " + letters.joinToString(", ")
            if (StudySettings.mimoConfigured) {
                val cached = cachedSpellingFile(app, word, letters)
                if (cached != null && cached.length() > 0) {
                    playFile(app, gen, "spell:$text", cached, onDone, deleteOnDone = false)
                    return@post
                }
                Thread({
                    val audio = runCatching { MimoClient.synthesizeSpelling(word, letters) }
                        .onFailure { Log.w(TAG, "MiMo spelling TTS failed; using Android TTS", it) }
                        .getOrNull()
                    main.post {
                        if (gen != generation) return@post
                        if (audio != null && audio.isNotEmpty()) {
                            val target = cachedSpellingFile(app, word, letters)
                            if (target != null && runCatching { target.writeBytes(audio) }.isSuccess) {
                                playFile(app, gen, "spell:$text", target, onDone, deleteOnDone = false)
                            } else {
                                playWav(app, gen, "spell:$text", audio, onDone)
                            }
                        } else {
                            androidSpeak(app, gen, text, onDone, Locale.ENGLISH)
                        }
                    }
                }, "study-spelling-tts").apply { isDaemon = true }.start()
            } else {
                androidSpeak(app, gen, text, onDone, Locale.ENGLISH)
            }
        }
    }

    private fun cachedSpellingFile(context: Context, word: String, letters: List<String>): File? = runCatching {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest("spelling|$word|${letters.joinToString(",")}|${StudySettings.mimoTtsModel}|${StudySettings.mimoVoice}".toByteArray())
            .joinToString("") { "%02x".format(it) }
        File(context.cacheDir, "study-spelling-$digest.wav")
    }.getOrNull()

    fun stop() {
        main.post {
            generation++
            releaseCurrent()
        }
    }

    private fun cachedFile(context: Context, text: String): File? = runCatching {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest("$text|${StudySettings.mimoTtsModel}|${StudySettings.mimoVoice}".toByteArray())
            .joinToString("") { "%02x".format(it) }
        File(context.cacheDir, "study-tts-$digest.wav")
    }.getOrNull()

    private fun playWav(context: Context, gen: Int, text: String, bytes: ByteArray, onDone: () -> Unit) {
        val file = runCatching { File.createTempFile("study-tts", ".wav", context.cacheDir) }.getOrNull()
        if (file == null) return androidSpeak(context, gen, text, onDone)
        runCatching { file.writeBytes(bytes) }.onFailure {
            file.delete()
            return androidSpeak(context, gen, text, onDone)
        }
        playFile(context, gen, text, file, onDone, deleteOnDone = true)
    }

    private fun playFile(
        context: Context,
        gen: Int,
        text: String,
        file: File,
        onDone: () -> Unit,
        deleteOnDone: Boolean,
    ) {
        val done = AtomicBoolean(false)
        fun finish() {
            if (!done.compareAndSet(false, true)) return
            if (gen != generation) return
            runCatching { player?.release() }
            player = null
            if (deleteOnDone) file.delete()
            main.post { if (gen == generation) onDone() }
        }
        val mp = MediaPlayer()
        player = mp
        runCatching {
            mp.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            mp.setDataSource(file.absolutePath)
            mp.setOnPreparedListener { if (gen == generation) it.start() else finish() }
            mp.setOnCompletionListener { finish() }
            mp.setOnErrorListener { _, _, _ ->
                Log.w(TAG, "TTS playback error; using Android TTS")
                finish()
                true
            }
            mp.prepareAsync()
        }.onFailure {
            finish()
            androidSpeak(context, gen, text, onDone)
        }
    }

    private fun androidSpeak(context: Context, gen: Int, text: String, onDone: () -> Unit, locale: Locale = Locale.SIMPLIFIED_CHINESE) {
        if (gen != generation) return
        val done = AtomicBoolean(false)
        fun finish() {
            if (!done.compareAndSet(false, true)) return
            if (gen != generation) return
            runCatching { tts?.shutdown() }
            tts = null
            main.post { if (gen == generation) onDone() }
        }
        var engine: TextToSpeech? = null
        engine = TextToSpeech(context) { status ->
            if (gen != generation) {
                runCatching { engine?.shutdown() }
                return@TextToSpeech
            }
            if (status != TextToSpeech.SUCCESS) {
                Log.w(TAG, "Android TTS unavailable")
                finish()
                return@TextToSpeech
            }
            engine?.language = locale
            engine?.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            engine?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) = Unit
                override fun onDone(utteranceId: String?) = finish()
                @Deprecated("Deprecated in Java")
                override fun onError(utteranceId: String?) = finish()
            })
            val result = engine?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "study-$gen")
            if (result == TextToSpeech.ERROR) finish()
        }
        tts = engine
    }

    private fun releaseCurrent() {
        runCatching { player?.stop() }
        runCatching { player?.release() }
        player = null
        runCatching { tts?.stop() }
        runCatching { tts?.shutdown() }
        tts = null
    }
}
