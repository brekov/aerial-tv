package app.orchard.tv.study

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import kotlin.math.sqrt

/** Debug-only microphone level probe used to validate the TV bottom mic before shipping Study Guard. */
object StudyMicProbe {
    fun start(context: Context) {
        Thread({
            val min = AudioRecord.getMinBufferSize(16_000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            val record = try {
                AudioRecord(MediaRecorder.AudioSource.MIC, 16_000, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, maxOf(min, 6400))
            } catch (t: Throwable) {
                Log.w("AerialStudy", "mic probe AudioRecord failed: ${t.javaClass.simpleName}")
                return@Thread
            }
            if (record.state != AudioRecord.STATE_INITIALIZED) {
                Log.w("AerialStudy", "mic probe state=${record.state}")
                record.release(); return@Thread
            }
            record.startRecording()
            Log.i("AerialStudy", "mic probe recording state=${record.recordingState} source=MIC")
            val buf = ShortArray(1600)
            var max = 0.0
            var sum = 0.0
            var n = 0L
            val until = System.currentTimeMillis() + 5_000
            while (System.currentTimeMillis() < until) {
                val r = record.read(buf, 0, buf.size)
                if (r <= 0) break
                for (i in 0 until r) {
                    val v = buf[i].toDouble()
                    max = maxOf(max, kotlin.math.abs(v))
                    sum += v * v
                    n++
                }
            }
            record.stop(); record.release()
            val rms = if (n == 0L) 0.0 else sqrt(sum / n)
            Log.i("AerialStudy", "mic probe rms=${"%.0f".format(rms)} max=${"%.0f".format(max)} samples=$n")
        }, "study-mic-probe").start()
    }
}
