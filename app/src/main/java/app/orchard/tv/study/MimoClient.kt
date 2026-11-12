package app.orchard.tv.study

import android.util.Base64
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Direct TV -> Xiaomi MiMo-V2.5 ASR/TTS client.
 *
 * The TV keeps its own MiMo key in StudySettings; this path does not touch the NAS. The APIs are
 * OpenAI-compatible chat completions: audio is supplied/returned as base64 in message content.
 */
object MimoClient {
    private const val TAG = "AerialStudy"

    fun transcribe(wav: ByteArray): String {
        val encoded = Base64.encodeToString(wav, Base64.NO_WRAP)
        val inputAudio = JSONObject()
            .put("type", "input_audio")
            .put("input_audio", JSONObject().put("data", "data:audio/wav;base64,$encoded"))
        val messages = JSONArray().put(
            JSONObject()
                .put("role", "user")
                .put("content", JSONArray().put(inputAudio)),
        )
        val body = JSONObject()
            .put("model", StudySettings.mimoAsrModel)
            .put("messages", messages)
            .put("asr_options", JSONObject().put("language", "auto"))
            .put("stream", false)
        val json = JSONObject(post(body))
        val message = json.optJSONArray("choices")?.optJSONObject(0)?.optJSONObject("message")
            ?: error("MiMo ASR: missing choices[0].message")
        val content = message.opt("content")
        val text = when (content) {
            is JSONArray -> (0 until content.length()).joinToString("") { content.optString(it) }
            null -> ""
            JSONObject.NULL -> ""
            else -> content.toString()
        }
        return text.trim()
    }

    fun synthesize(text: String): ByteArray {
        val messages = JSONArray()
            .put(JSONObject().put("role", "user").put("content", "请自然地朗读下面这句话。"))
            .put(JSONObject().put("role", "assistant").put("content", text))
        val body = JSONObject()
            .put("model", StudySettings.mimoTtsModel)
            .put("messages", messages)
            .put("audio", JSONObject().put("format", "wav").put("voice", StudySettings.mimoVoice))
            .put("stream", false)
        val json = JSONObject(post(body))
        val audio = json.optJSONArray("choices")?.optJSONObject(0)
            ?.optJSONObject("message")?.optJSONObject("audio")
            ?: error("MiMo TTS: missing choices[0].message.audio")
        val data = audio.optString("data")
        if (data.isBlank()) error("MiMo TTS returned empty audio")
        val base64 = if (data.startsWith("data:")) data.substringAfter(',') else data
        return Base64.decode(base64, Base64.DEFAULT)
    }

    /** English-only word reference; keeps the target out of the Chinese instruction sentence. */
    fun synthesizeWord(word: String): ByteArray {
        val messages = JSONArray()
            .put(JSONObject().put("role", "user").put("content", "Read this English word aloud naturally and clearly. Do not translate or transliterate it."))
            .put(JSONObject().put("role", "assistant").put("content", word))
        val body = JSONObject()
            .put("model", StudySettings.mimoTtsModel)
            .put("messages", messages)
            .put("audio", JSONObject().put("format", "wav").put("voice", StudySettings.mimoVoice))
            .put("stream", false)
        val json = JSONObject(post(body))
        val audio = json.optJSONArray("choices")?.optJSONObject(0)
            ?.optJSONObject("message")?.optJSONObject("audio")
            ?: error("MiMo TTS: missing choices[0].message.audio")
        val data = audio.optString("data")
        if (data.isBlank()) error("MiMo TTS returned empty audio")
        val base64 = if (data.startsWith("data:")) data.substringAfter(',') else data
        return Base64.decode(base64, Base64.DEFAULT)
    }

    fun synthesizeSpelling(word: String, letters: List<String>): ByteArray {
        val text = word + ", " + letters.joinToString(", ")
        val messages = JSONArray()
            .put(JSONObject().put("role", "user").put("content", "Read this English word, then spell it slowly and clearly. Do not translate."))
            .put(JSONObject().put("role", "assistant").put("content", text))
        val body = JSONObject()
            .put("model", StudySettings.mimoTtsModel)
            .put("messages", messages)
            .put("audio", JSONObject().put("format", "wav").put("voice", StudySettings.mimoVoice))
            .put("stream", false)
        val json = JSONObject(post(body))
        val audio = json.optJSONArray("choices")?.optJSONObject(0)
            ?.optJSONObject("message")?.optJSONObject("audio")
            ?: error("MiMo TTS: missing choices[0].message.audio")
        val data = audio.optString("data")
        if (data.isBlank()) error("MiMo TTS returned empty audio")
        val base64 = if (data.startsWith("data:")) data.substringAfter(',') else data
        return Base64.decode(base64, Base64.DEFAULT)
    }

    private fun post(body: JSONObject): String {
        val endpoint = StudySettings.mimoBaseUrl.trimEnd('/') + "/chat/completions"
        val connection = URL(endpoint).openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.connectTimeout = 8_000
        connection.readTimeout = 60_000
        connection.setRequestProperty("Content-Type", "application/json")
        connection.setRequestProperty("Accept", "application/json")
        // MiMo documents both api-key and Bearer; api-key is the form used by the audio guide.
        connection.setRequestProperty("api-key", StudySettings.mimoApiKey)
        connection.doOutput = true
        connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code !in 200..299) {
            Log.w(TAG, "MiMo HTTP $code: ${response.take(300)}")
            error("MiMo HTTP $code")
        }
        return response
    }
}
