package app.orchard.tv.study

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Small HTTP client for the LAN aerial-study service. All calls are blocking; use a worker. */
object StudyClient {
    data class Question(
        val id: Long,
        val type: String,
        val imageUrl: String?,
        val text: String?,
        val say: String?,
        val answerMode: String = "voice",
        val options: List<String> = emptyList(),
    )
    data class Session(val id: String, val questions: List<Question>)
    data class UploadToken(val url: String, val expiresAt: String)
    data class Answer(
        val correct: Boolean,
        val score: Int,
        val pronunciationOverall: Int?,
        val mimoVerdict: String?,
        val progress: Int,
        val finished: Boolean,
        val restart: Boolean,
        val retry: Boolean,
    )

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

    fun startSession(): Session {
        val c = open("/api/v1/sessions", "POST")
        c.doOutput = true
        c.outputStream.use { it.write("{}".toByteArray()) }
        val json = JSONObject(read(c))
        val session = json.optJSONObject("session")?.optString("id") ?: json.optString("session")
        val questions = json.getJSONArray("questions")
        return Session(session, (0 until questions.length()).map { i ->
            val q = questions.getJSONObject(i)
            val promptObj = q.optJSONObject("prompt")
            val promptText = promptObj?.optString("text") ?: q.optString("prompt").takeIf { it.isNotBlank() }
            val image = promptObj?.optString("imageUrl")?.takeIf { it.isNotBlank() }?.let {
                if (it.startsWith("http")) it else base() + it
            }
            Question(
                q.getLong("id"),
                q.optString("type", "word_image"),
                q.optString("imageUrl").takeIf { it.isNotBlank() } ?: image,
                promptText,
                q.optString("say").takeIf { it.isNotBlank() },
                q.optString("answerMode", "voice"),
                q.optJSONArray("options")?.let { arr -> (0 until arr.length()).map { arr.optString(it) } } ?: emptyList(),
            )
        })
    }

    fun answer(
        session: String,
        question: Long,
        transcript: String,
        wav: ByteArray? = null,
        selectedOption: Int? = null,
    ): Answer {
        val c = open("/api/v1/sessions/$session/answer", "POST")
        c.doOutput = true
        val body = JSONObject().put("questionId", question).put("transcript", transcript)
        if (wav != null) {
            body.put("audio", Base64.encodeToString(wav, Base64.NO_WRAP))
            body.put("audioFormat", "audio/wav")
        }
        if (selectedOption != null) body.put("selectedOption", selectedOption)
        c.outputStream.use { it.write(body.toString().toByteArray()) }
        val json = JSONObject(read(c))
        val progress = json.optJSONObject("progress")
        val pronunciation = json.optJSONObject("pronunciation")
        val mimo = json.optJSONObject("mimoJudge")
        return Answer(
            correct = json.optBoolean("correct"),
            score = json.optInt("score", 0).coerceIn(0, 100),
            pronunciationOverall = pronunciation?.optInt("overall", -1)?.takeIf { it >= 0 }?.coerceIn(0, 100),
            mimoVerdict = mimo?.optString("verdict")?.takeIf { it.isNotBlank() },
            progress = progress?.optInt("currentIndex") ?: 0,
            finished = json.optBoolean("finished"),
            restart = json.optBoolean("restart"),
            retry = json.optBoolean("retry"),
        )
    }

    /** Short-lived phone upload URL for materials; TV device token authorises it. */
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

    fun transcribe(wav: ByteArray): String {
        val boundary = "AerialStudy" + System.nanoTime().toString(16)
        val head = ("--$boundary\r\n" +
            "Content-Disposition: form-data; name=\"file\"; filename=\"answer.wav\"\r\n" +
            "Content-Type: audio/wav\r\n\r\n").toByteArray()
        val tail = "\r\n--$boundary--\r\n".toByteArray()
        val c = open("/api/v1/asr", "POST", "multipart/form-data; boundary=$boundary")
        c.doOutput = true
        c.setFixedLengthStreamingMode(head.size + wav.size + tail.size)
        c.outputStream.use { it.write(head); it.write(wav); it.write(tail) }
        return JSONObject(read(c)).optString("text").trim()
    }

    fun loadImage(url: String): Bitmap? = runCatching {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 5_000
        c.readTimeout = 10_000
        c.setRequestProperty("X-Study-Token", StudySettings.deviceToken)
        c.inputStream.use { BitmapFactory.decodeStream(it) }
    }.getOrNull()
}
