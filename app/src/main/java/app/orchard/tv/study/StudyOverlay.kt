package app.orchard.tv.study

import android.content.ComponentName
import android.content.res.ColorStateList
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import app.orchard.tv.R
import app.orchard.tv.guard.HomeGuardService
import app.orchard.tv.system.DiagLog
import java.util.concurrent.Executors

/**
 * Full-screen quiz drawn by the accessibility service, over whatever app is in front.
 *
 * It does not start an Activity: the video app stays in the background, its audio is paused or
 * muted for the quiz, and removing the overlay returns to it. The recognition service resolves to
 * Aerial's own [AerialRecognitionService]; no phone microphone and no Xiaomi voice assistant.
 */
class StudyOverlay internal constructor(private val service: HomeGuardService) {
    companion object {
        private const val TAG = "AerialStudy"
        private val main = Handler(Looper.getMainLooper())
        private var instance: StudyOverlay? = null

        @Volatile var active = false
            private set

        /** Called from StudyWatch: false when Home Guard is not bound. */
        fun show(context: Context): Boolean {
            if (!StudySettings.enabled) return false
            val service = HomeGuardService.studyService() ?: return false
            if (instance == null) {
                val overlay = StudyOverlay(service)
                instance = overlay
                overlay.show()
            }
            return true
        }

        fun dismiss() {
            instance?.dismissFromOutside()
            instance = null
        }
    }

    private val wm = service.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val audio = service.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val io = Executors.newSingleThreadExecutor()
    private lateinit var root: FrameLayout
    private lateinit var image: ImageView
    private lateinit var title: TextView
    private lateinit var progress: ProgressBar
    private lateinit var status: TextView
    private var speech: SpeechRecognizer? = null
    private var session: StudyClient.Session? = null
    private var index = 0
    private var listening = false
    private var closed = false
    private var attempt = 0
    private var oldVolume = -1
    private var oldMute = false
    private var hasFocus = false

    private val timeout = Runnable { if (!closed) retry("timeout") }
    private val pass = Runnable { finish(true) }

    internal fun show() {
        if (active) return
        if (!StudySettings.enabled) return
        active = true
        closed = false
        index = 0
        attempt = 0
        build()
        pauseAudio()
        HomeGuardService.studyOverlayChanged()
        startSession()
        DiagLog.i("study: overlay shown")
    }

    private fun build() {
        root = FrameLayout(service).apply {
            setBackgroundColor(Color.rgb(18, 18, 22))
            isFocusable = true
            isFocusableInTouchMode = true
            setOnKeyListener { _, keyCode, _ -> keyCode != KeyEvent.KEYCODE_POWER }
        }
        // The card is the exercise. The top strip owns its own space instead of covering the
        // image; below it the image gets all remaining width and height.
        val column = LinearLayout(service).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.BLACK)
        }
        val header = LinearLayout(service).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.START
            setPadding(48, 14, 48, 12)
            setBackgroundColor(Color.rgb(18, 18, 22))
        }
        title = text(22f, Color.WHITE, Typeface.BOLD).apply { text = service.getString(R.string.study_title) }
        val density = service.resources.displayMetrics.density
        progress = ProgressBar(service, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = false
            max = StudySettings.QUESTIONS
            progressTintList = ColorStateList.valueOf(Color.rgb(92, 164, 255))
            progressBackgroundTintList = ColorStateList.valueOf(Color.rgb(49, 54, 66))
            minimumHeight = (3 * density).toInt().coerceAtLeast(2)
        }
        status = text(17f, Color.LTGRAY, Typeface.NORMAL).apply {
            gravity = Gravity.START
            visibility = View.GONE
        }
        header.addView(title)
        header.addView(progress, LinearLayout.LayoutParams(-1, (3 * density).toInt().coerceAtLeast(2)).apply { topMargin = 10 })
        header.addView(status, LinearLayout.LayoutParams(-1, -2).apply { topMargin = 6 })
        column.addView(header, LinearLayout.LayoutParams(-1, -2))
        image = ImageView(service).apply {
            scaleType = ImageView.ScaleType.FIT_CENTER
            setBackgroundColor(Color.BLACK)
        }
        column.addView(image, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(column, FrameLayout.LayoutParams(-1, -1))
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_DIM_BEHIND,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            dimAmount = 0.8f
            title = "Aerial study"
        }
        wm.addView(root, lp)
        root.requestFocus()
    }

    private fun text(size: Float, color: Int, style: Int) = TextView(service).apply {
        textSize = size
        setTextColor(color)
        typeface = Typeface.create(Typeface.DEFAULT, style)
    }

    private fun startSession() {
        status.text = service.getString(R.string.study_loading)
        io.execute {
            val result = runCatching { StudyClient.startSession() }
            main.post {
                if (closed) return@post
                result.onSuccess { s ->
                    session = s
                    index = 0
                    attempt = 0
                    if (s.questions.isEmpty()) {
                        status.text = service.getString(R.string.study_error)
                        status.visibility = View.VISIBLE
                        retryLater()
                    } else {
                        showQuestion()
                    }
                }.onFailure {
                    Log.w(TAG, "study session failed", it)
                    status.text = service.getString(R.string.study_error)
                    status.visibility = View.VISIBLE
                    retryLater()
                }
            }
        }
    }

    private fun showQuestion() {
        val s = session ?: return
        val q = s.questions.getOrNull(index) ?: return finish(false)
        progress.max = s.questions.size
        progress.progress = index + 1
        status.visibility = View.GONE
        image.setImageBitmap(null)
        if (q.text != null) title.text = q.text else title.text = service.getString(R.string.study_title)
        if (q.imageUrl != null) io.execute {
            val bmp: Bitmap? = StudyClient.loadImage(q.imageUrl)
            main.post { if (!closed) image.setImageBitmap(bmp) }
        }
        listen()
        main.removeCallbacks(timeout)
        main.postDelayed(timeout, 120_000)
    }

    private fun listen() {
        if (closed) return
        stopSpeech()
        val component = ComponentName(service, AerialRecognitionService::class.java)
        val recognizer = if (SpeechRecognizer.isRecognitionAvailable(service)) {
            SpeechRecognizer.createSpeechRecognizer(service, component)
        } else {
            SpeechRecognizer.createSpeechRecognizer(service, component)
        }
        speech = recognizer
        listening = true
        status.visibility = View.GONE
        recognizer.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: android.os.Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onError(error: Int) {
                if (closed) return
                listening = false
                when (error) {
                    SpeechRecognizer.ERROR_NO_MATCH,
                    SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
                    SpeechRecognizer.ERROR_CLIENT -> retry("no speech")
                    else -> retry("recognizer $error")
                }
            }
            override fun onResults(results: android.os.Bundle?) {
                if (closed) return
                listening = false
                val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                if (text.isBlank()) retry("empty") else submit(text)
            }
            override fun onPartialResults(partialResults: android.os.Bundle?) {}
            override fun onEvent(eventType: Int, params: android.os.Bundle?) {}
        })
        val intent = android.content.Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }
        runCatching { recognizer.startListening(intent) }.onFailure {
            Log.w(TAG, "startListening", it)
            retry("microphone")
        }
    }

    private fun submit(transcript: String) {
        val s = session ?: return
        val q = s.questions.getOrNull(index) ?: return
        status.text = service.getString(R.string.study_recognizing)
        status.visibility = View.GONE
        main.removeCallbacks(timeout)
        io.execute {
            val answer = runCatching { StudyClient.answer(s.id, q.id, transcript) }
            main.post {
                if (closed) return@post
                answer.onSuccess { a ->
                    if (a.restart || !a.correct) {
                        status.text = service.getString(R.string.study_wrong)
                        status.visibility = View.VISIBLE
                        main.postDelayed({ if (!closed) startSession() }, 2_000)
                        return@post
                    }
                    index = a.progress
                    if (a.finished || index >= s.questions.size) {
                        status.text = service.getString(R.string.study_passed)
                        status.visibility = View.VISIBLE
                        main.removeCallbacks(timeout)
                        main.postDelayed(pass, 1_500)
                    } else {
                        status.text = service.getString(R.string.study_right)
                        status.visibility = View.VISIBLE
                        main.postDelayed({ if (!closed) showQuestion() }, 600)
                    }
                }.onFailure {
                    Log.w(TAG, "answer failed", it)
                    status.text = service.getString(R.string.study_error)
                    status.visibility = View.VISIBLE
                    retryLater()
                }
            }
        }
    }

    private fun retry(reason: String) {
        if (closed) return
        stopSpeech()
        attempt++
        DiagLog.i("study: retry $attempt ($reason)")
        status.text = if (reason == "no speech" || reason == "empty") {
            service.getString(R.string.study_no_speech)
        } else {
            service.getString(R.string.study_error)
        }
        status.visibility = View.VISIBLE
        if (attempt <= 3) main.postDelayed({ if (!closed) listen() }, 900)
        else retryLater()
    }

    private fun retryLater() {
        main.removeCallbacks(timeout)
        main.postDelayed({ if (!closed) startSession() }, 5_000)
    }

    private fun finish(passed: Boolean) {
        if (closed) return
        closed = true
        active = false
        main.removeCallbacks(timeout)
        main.removeCallbacks(pass)
        stopSpeech()
        if (passed) StudySettings.resetWatch()
        main.post {
            remove()
            restoreAudio()
            HomeGuardService.studyOverlayChanged()
        }
        DiagLog.i(if (passed) "study: passed" else "study: closed")
        instance = null
    }

    private fun remove() {
        runCatching { wm.removeView(root) }
    }

    private fun stopSpeech() {
        val r = speech ?: return
        speech = null
        runCatching { r.stopListening() }
        runCatching { r.cancel() }
        runCatching { r.destroy() }
        listening = false
    }

    private fun pauseAudio() {
        runCatching {
            oldVolume = audio.getStreamVolume(AudioManager.STREAM_MUSIC)
            oldMute = Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && audio.isStreamMute(AudioManager.STREAM_MUSIC)
            val event = android.view.KeyEvent(android.view.KeyEvent.ACTION_DOWN, android.view.KeyEvent.KEYCODE_MEDIA_PAUSE)
            audio.dispatchMediaKeyEvent(event)
            audio.dispatchMediaKeyEvent(android.view.KeyEvent(android.view.KeyEvent.ACTION_UP, android.view.KeyEvent.KEYCODE_MEDIA_PAUSE))
            @Suppress("DEPRECATION")
            hasFocus = audio.requestAudioFocus(null, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT) ==
                AudioManager.AUDIOFOCUS_REQUEST_GRANTED
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, 0)
        }
    }

    private fun restoreAudio() {
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                if (oldMute) audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, 0)
                else {
                    audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_UNMUTE, 0)
                    if (oldVolume >= 0) audio.setStreamVolume(AudioManager.STREAM_MUSIC, oldVolume, 0)
                }
            }
            if (hasFocus) {
                @Suppress("DEPRECATION")
                audio.abandonAudioFocus(null)
            }
            oldVolume = -1
            hasFocus = false
        }
    }

    fun dismissFromOutside() {
        if (!closed) finish(false)
    }
}
