package app.orchard.tv.study

/** Holds the one short WAV captured for the current attempt; cleared after upload. */
object StudyAudioBus {
    @Volatile private var wav: ByteArray? = null
    @Volatile private var stamp: Long = 0L

    fun put(bytes: ByteArray) {
        wav = bytes
        stamp = System.currentTimeMillis()
    }

    fun take(): ByteArray? {
        val value = wav
        wav = null
        return value
    }

    fun clear() {
        wav = null
    }

    fun ageMs(): Long = if (wav == null) Long.MAX_VALUE else System.currentTimeMillis() - stamp
}
