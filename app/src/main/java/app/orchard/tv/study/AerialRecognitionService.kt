package app.orchard.tv.study

import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionService
import android.speech.SpeechRecognizer
import android.util.Log
import java.io.ByteArrayOutputStream
import java.util.ArrayDeque
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs
import kotlin.math.sqrt

/**
 * A real Android RecognitionService backed by the TV's own microphone and the LAN Whisper service.
 *
 * Google's recognizer is not installed on the Xiaomi MFTR0 and the Xiaomi voice assistant is
 * private, so Aerial resolves its own RecognitionService explicitly (StudyOverlay). The service is
 * also exported as a standard component for other clients.
 *
 * Audio is captured at 16 kHz mono with a small adaptive-energy VAD. With a MiMo key configured
 * the utterance goes directly from the TV to MiMo-V2.5-ASR; otherwise it falls back to the LAN
 * /api/v1/asr service. No audio is stored.
 */
class AerialRecognitionService : RecognitionService() {
    companion object {
        private const val TAG = "AerialStudy"
        private const val SAMPLE_RATE = 16_000
        private const val FRAME_SAMPLES = 320 // 20 ms
        private const val PRE_ROLL_FRAMES = 15 // 300 ms
        private const val START_FRAMES = 3
        private const val STOP_SILENCE_FRAMES = 60 // 1.2 s
        private const val MAX_FRAMES = 400 // 8 s
        private const val NO_SPEECH_FRAMES = 300 // 6 s
        private val main = Handler(Looper.getMainLooper())
    }

    private var worker: Thread? = null
    private val cancelled = AtomicBoolean(false)
    private var record: AudioRecord? = null

    override fun onStartListening(intent: Intent?, listener: Callback) {
        stopWorker()
        cancelled.set(false)
        StudySettings.init(this)
        listener.readyForSpeech(Bundle())
        worker = Thread({ capture(listener) }, "aerial-recognition").also { it.start() }
    }

    override fun onStopListening(listener: Callback) {
        cancelled.set(true)
        stopWorker()
    }

    override fun onCancel(listener: Callback) {
        cancelled.set(true)
        stopWorker()
    }

    override fun onDestroy() {
        stopWorker()
        super.onDestroy()
    }

    private fun stopWorker() {
        cancelled.set(true)
        runCatching { record?.stop() }
        runCatching { record?.release() }
        record = null
        worker?.interrupt()
        worker = null
    }

    private fun capture(listener: Callback) {
        val min = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (min <= 0) return fail(listener, "no audio buffer")
        val recorder = try {
            AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                maxOf(min, FRAME_SAMPLES * 2 * 4),
            )
        } catch (t: Throwable) {
            return fail(listener, "AudioRecord: ${t.javaClass.simpleName}")
        }
        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            return fail(listener, "microphone unavailable")
        }
        record = recorder
        try {
            recorder.startRecording()
        } catch (t: Throwable) {
            recorder.release()
            record = null
            return fail(listener, "startRecording: ${t.javaClass.simpleName}")
        }

        val frame = ShortArray(FRAME_SAMPLES)
        val preRoll = ArrayDeque<ShortArray>()
        val utterance = ByteArrayOutputStream()
        var noise = 400.0
        var speechFrames = 0
        var silenceFrames = 0
        var consecutiveSpeech = 0
        var started = false
        var frames = 0

        try {
            while (!cancelled.get() && frames < NO_SPEECH_FRAMES + MAX_FRAMES) {
                val read = recorder.read(frame, 0, frame.size)
                if (read <= 0) break
                frames++
                val rms = rms(frame)
                val active = rms > maxOf(noise * 3.0, 300.0)
                if (!started) {
                    if (!active) noise = noise * 0.95 + rms * 0.05
                    consecutiveSpeech = if (active) consecutiveSpeech + 1 else 0
                    if (consecutiveSpeech >= START_FRAMES) {
                        started = true
                        speechFrames = 0
                        silenceFrames = 0
                        main.post { listener.beginningOfSpeech() }
                        while (preRoll.isNotEmpty()) writeShorts(utterance, preRoll.removeFirst())
                    } else {
                        preRoll.addLast(frame.copyOf())
                        while (preRoll.size > PRE_ROLL_FRAMES) preRoll.removeFirst()
                    }
                    if (!started && frames >= NO_SPEECH_FRAMES) return fail(listener, "no speech")
                    continue
                }
                writeShorts(utterance, frame)
                speechFrames++
                main.post { listener.rmsChanged(rms.toFloat().coerceIn(-2f, 10f)) }
                if (active) silenceFrames = 0 else silenceFrames++
                if (silenceFrames >= STOP_SILENCE_FRAMES || speechFrames >= MAX_FRAMES) break
            }
            if (!started || speechFrames < 30) return fail(listener, "too short")
            main.post { listener.endOfSpeech() }
            val wav = wav(utterance.toByteArray())
            val text = (if (StudySettings.mimoConfigured) {
                runCatching { MimoClient.transcribe(wav) }
            } else {
                runCatching { StudyClient.transcribe(wav) }
            }).getOrElse {
                Log.w(TAG, "ASR failed", it)
                return fail(listener, "ASR unavailable")
            }
            if (text.isBlank()) return fail(listener, "no match")
            val results = Bundle().apply {
                putStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION, arrayListOf(text))
                putFloatArray(SpeechRecognizer.CONFIDENCE_SCORES, floatArrayOf(1f))
            }
            main.post { if (!cancelled.get()) listener.results(results) }
        } finally {
            runCatching { recorder.stop() }
            runCatching { recorder.release() }
            record = null
        }
    }

    private fun fail(listener: Callback, reason: String) {
        Log.w(TAG, "recognition: $reason")
        main.post {
            if (!cancelled.get()) listener.error(
                when {
                    reason.contains("speech", true) || reason.contains("short", true) -> SpeechRecognizer.ERROR_NO_MATCH
                    reason.contains("ASR", true) -> SpeechRecognizer.ERROR_NETWORK
                    else -> SpeechRecognizer.ERROR_AUDIO
                },
            )
        }
    }

    private fun rms(frame: ShortArray): Double {
        var sum = 0.0
        for (v in frame) sum += (v.toDouble() * v)
        return sqrt(sum / frame.size)
    }

    private fun writeShorts(out: ByteArrayOutputStream, data: ShortArray) {
        val bytes = ByteArray(data.size * 2)
        var j = 0
        for (v in data) {
            bytes[j++] = (v.toInt() and 0xff).toByte()
            bytes[j++] = ((v.toInt() shr 8) and 0xff).toByte()
        }
        out.write(bytes)
    }

    private fun wav(pcm: ByteArray): ByteArray {
        val out = ByteArrayOutputStream(44 + pcm.size)
        fun le32(v: Int) { out.write(byteArrayOf((v and 0xff).toByte(), ((v shr 8) and 0xff).toByte(), ((v shr 16) and 0xff).toByte(), ((v shr 24) and 0xff).toByte())) }
        fun le16(v: Int) { out.write(byteArrayOf((v and 0xff).toByte(), ((v shr 8) and 0xff).toByte())) }
        out.write("RIFF".toByteArray()); le32(36 + pcm.size); out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); le32(16); le16(1); le16(1); le32(SAMPLE_RATE); le32(SAMPLE_RATE * 2); le16(2); le16(16)
        out.write("data".toByteArray()); le32(pcm.size); out.write(pcm)
        return out.toByteArray()
    }
}
