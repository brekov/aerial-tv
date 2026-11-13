package app.orchard.tv.study

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import android.util.Base64
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Small HTTP client for the LAN aerial-study service. All calls are blocking; use a worker. */
object StudyClient {
    data class RepeatCard(
        val id: Long,
        val imageUrl: String?,
        val word: String,
    )
    data class RepeatSession(
        val id: String,
        val status: String,
        val total: Int,
        val cards: List<RepeatCard>,
    )
    data class RepeatResult(
        val score: Int,
        val verdict: String,
        val heard: String,
        val feedback: String,
        val retry: Boolean,
        val finished: Boolean,
        val totalScore: Int,
        val nextCard: RepeatCard?,
    )
    data class UploadToken(val url: String, val expiresAt: String)

    private fun base() = StudySettings.baseUrl.trimEnd('/')

    private fun open(path: String, method: String = "GET", type: String = "application/json"): HttpURLConnection {
        val c = URL(base() + path).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 8_000
        c.readTimeout = 25_000
        c.setRequestProperty("Accept", "application/json")
        c.setRequestProperty("X-Study-Token", StudySettings.deviceToken)
        if (method != "GET") c.setRequestProperty("Content-Type", type)
        return c
    }

    private fun read(c: HttpURLConnection): String {
        val stream = if (c.responseCode in 200..299) c.inputStream else c.errorStream
        val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (c.responseCode !in 200..299) error("HTTP ${c.responseCode}: $body")
        return body
    }

    fun startRepeatSession(): RepeatSession {
        val c = open("/api/v1/repeat-learning/sessions", "POST")
        c.doOutput = true
        c.outputStream.use { it.write("{}".toByteArray()) }
        val json = JSONObject(read(c))
        val session = json.getJSONObject("session")
        val cards = json.getJSONArray("cards")
        fun card(obj: JSONObject): RepeatCard = RepeatCard(
            obj.getLong("id"),
            obj.optString("imageUrl").takeIf { it.isNotBlank() }?.let {
                if (it.startsWith("http")) it else base() + it
            },
            obj.optString("word"),
        )
        return RepeatSession(
            session.optString("id"),
            session.optString("status", "active"),
            session.optInt("total", 3),
            (0 until cards.length()).map { card(cards.getJSONObject(it)) },
        )
    }

    fun submitRepeatAttempt(session: String, cardId: Long, wav: ByteArray): RepeatResult {
        val c = open("/api/v1/repeat-learning/sessions/$session/attempts", "POST")
        c.doOutput = true
        val body = JSONObject()
            .put("cardId", cardId)
            .put("audio", Base64.encodeToString(wav, Base64.NO_WRAP))
            .put("audioFormat", "audio/wav")
        c.outputStream.use { it.write(body.toString().toByteArray()) }
        val json = JSONObject(read(c))
        val next = json.optJSONObject("nextCard")?.let { obj ->
            RepeatCard(
                obj.getLong("id"),
                obj.optString("imageUrl").takeIf { it.isNotBlank() }?.let {
                    if (it.startsWith("http")) it else base() + it
                },
                obj.optString("word"),
            )
        }
        return RepeatResult(
            json.optInt("score", 0).coerceIn(0, 100),
            json.optString("verdict"),
            json.optString("heard"),
            json.optString("feedback"),
            json.optBoolean("retry"),
            json.optBoolean("finished"),
            json.optInt("totalScore", 0),
            next,
        )
    }

    fun createUploadToken(): UploadToken? = runCatching {
        val c = open("/api/v1/study/upload-tokens", "POST")
        c.doOutput = true
        val body = JSONObject().put("maxUploads", 10).put("minutes", 10).toString()
        c.outputStream.use { it.write(body.toByteArray()) }
        val token = JSONObject(read(c)).optJSONObject("token") ?: return@runCatching null
        val url = token.optString("url")
        if (url.isBlank()) return@runCatching null
        UploadToken(url, token.optString("expiresAt"))
    }.getOrNull()

    fun loadImage(url: String): Bitmap? = runCatching {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 5_000
        c.readTimeout = 10_000
        c.setRequestProperty("X-Study-Token", StudySettings.deviceToken)
        val code = c.responseCode
        if (code !in 200..299) {
            Log.w("AerialStudy", "repeat image HTTP $code: $url")
            return@runCatching null
        }
        c.inputStream.use { BitmapFactory.decodeStream(it) }.also {
            if (it == null) Log.w("AerialStudy", "repeat image decode failed: $url")
        }
    }.onFailure { Log.w("AerialStudy", "repeat image load failed: $url", it) }.getOrNull()
}
