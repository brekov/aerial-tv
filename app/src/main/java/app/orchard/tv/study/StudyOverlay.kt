package app.orchard.tv.study

import android.animation.ValueAnimator
import android.content.ComponentName
import android.content.res.ColorStateList
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.text.TextUtils
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.view.animation.LinearInterpolator
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
    private lateinit var cue: ImageView
    private var cueAnimator: ValueAnimator? = null
    private enum class Cue { LISTEN, SPEAK, PROCESS, CHECK, CROSS }
    private var speech: SpeechRecognizer? = null
    private var session: StudyClient.Session? = null
    private var index = 0
    private var listening = false
    private var listenGeneration = 0
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
        val density = service.resources.displayMetrics.density
        val header = LinearLayout(service).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 8, 48, 10)
            setBackgroundColor(Color.rgb(18, 18, 22))
        }
        val titleRow = LinearLayout(service).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        title = text(22f, Color.WHITE, Typeface.BOLD).apply {
            text = service.getString(R.string.study_title)
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
        }
        status = text(15f, Color.LTGRAY, Typeface.NORMAL).apply {
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
            setPadding(16, 0, 0, 0)
            maxWidth = (service.resources.displayMetrics.widthPixels * 0.46f).toInt()
            visibility = View.INVISIBLE
        }
        titleRow.addView(title, LinearLayout.LayoutParams(0, -2, 1f))
        titleRow.addView(status, LinearLayout.LayoutParams(-2, -2))
        progress = ProgressBar(service, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = false
            max = StudySettings.QUESTIONS
            progressTintList = ColorStateList.valueOf(Color.rgb(92, 164, 255))
            progressBackgroundTintList = ColorStateList.valueOf(Color.rgb(49, 54, 66))
            minimumHeight = (3 * density).toInt().coerceAtLeast(2)
        }
        header.addView(titleRow, LinearLayout.LayoutParams(-1, -2))
        header.addView(progress, LinearLayout.LayoutParams(-1, (3 * density).toInt().coerceAtLeast(2)).apply { topMargin = 8 })
        // Fixed header height: showing feedback must not reflow or shrink the image.
        column.addView(header, LinearLayout.LayoutParams(-1, (72 * density).toInt()))
        image = ImageView(service).apply {
            scaleType = ImageView.ScaleType.FIT_CENTER
            setBackgroundColor(Color.BLACK)
        }
        column.addView(image, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(column, FrameLayout.LayoutParams(-1, -1))
        val cueSize = (176 * density).toInt()
        cue = ImageView(service).apply {
            setBackground(GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.argb(115, 0, 0, 0))
                setStroke((2 * density).toInt().coerceAtLeast(2), Color.argb(150, 255, 255, 255))
            })
            setPadding((34 * density).toInt(), (34 * density).toInt(), (34 * density).toInt(), (34 * density).toInt())
            visibility = View.INVISIBLE
            contentDescription = "Study cue"
        }
        root.addView(cue, FrameLayout.LayoutParams(cueSize, cueSize, Gravity.END or Gravity.CENTER_VERTICAL).apply {
            rightMargin = (54 * density).toInt()
        })
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

    /** Big, animated non-text cue so a child can see whether to listen, speak or wait. */
    private fun showCue(mode: Cue) {
        if (!::cue.isInitialized || closed) return
        cue.visibility = View.VISIBLE
        cue.setImageResource(
            when (mode) {
                Cue.LISTEN -> R.drawable.study_cue_speaker
                Cue.SPEAK -> R.drawable.study_cue_mic
                Cue.PROCESS -> R.drawable.study_cue_processing
                Cue.CHECK -> R.drawable.study_cue_check
                Cue.CROSS -> R.drawable.study_cue_cross
            }
        )
        cueAnimator?.cancel()
        cue.rotation = 0f
        cue.scaleX = 1f
        cue.scaleY = 1f
        cue.alpha = 1f
        cueAnimator = when (mode) {
            Cue.PROCESS -> ValueAnimator.ofFloat(0f, 360f).apply {
                duration = 1_000
                repeatCount = ValueAnimator.INFINITE
                interpolator = LinearInterpolator()
                addUpdateListener { cue.rotation = it.animatedValue as Float }
            }
            Cue.CHECK, Cue.CROSS -> ValueAnimator.ofFloat(0.7f, 1.1f).apply {
                duration = 220
                addUpdateListener {
                    val scale = it.animatedValue as Float
                    cue.scaleX = scale
                    cue.scaleY = scale
                }
            }
            else -> ValueAnimator.ofFloat(1f, 1.16f).apply {
                duration = 520
                repeatMode = ValueAnimator.REVERSE
                repeatCount = ValueAnimator.INFINITE
                addUpdateListener {
                    val scale = it.animatedValue as Float
                    cue.scaleX = scale
                    cue.scaleY = scale
                }
            }
        }.also { it.start() }
    }

    private fun hideCue() {
        if (!::cue.isInitialized) return
        cueAnimator?.cancel()
        cueAnimator = null
        cue.visibility = View.INVISIBLE
    }

    private fun startSession() {
        status.text = service.getString(R.string.study_loading)
        status.visibility = View.VISIBLE
        io.execute {
            val result = runCatching { StudyClient.startSession() }
            main.post {
                if (closed) return@post
                result.onSuccess { s ->
                    session = s
                    index = 0
                    attempt = 0
                    if (s.questions.isEmpty()) {
                        showCue(Cue.CROSS)
                        announce(R.string.study_voice_error) { retryLater() }
                    } else {
                        showQuestion()
                    }
                }.onFailure {
                    Log.w(TAG, "study session failed", it)
                    showCue(Cue.CROSS)
                    announce(R.string.study_voice_error) { retryLater() }
                }
            }
        }
    }

    private fun showQuestion() {
        val s = session ?: return
        val q = s.questions.getOrNull(index) ?: return finish(false)
        stopSpeech()
        progress.max = s.questions.size
        progress.progress = index + 1
        status.visibility = View.INVISIBLE
        image.setImageBitmap(null)
        if (q.text != null) title.text = q.text else title.text = service.getString(R.string.study_title)
        if (q.imageUrl != null) io.execute {
            val bmp: Bitmap? = StudyClient.loadImage(q.imageUrl)
            main.post { if (!closed) image.setImageBitmap(bmp) }
        }
        main.removeCallbacks(timeout)
        main.postDelayed(timeout, 120_000)
        showCue(Cue.LISTEN)
        if (!q.say.isNullOrBlank()) {
            status.text = service.getString(R.string.study_listen_first)
            status.setTextColor(Color.WHITE)
            status.visibility = View.VISIBLE
            // One spoken instruction includes the model word, so a pre-reader knows what follows.
            StudyVoice.speak(service, service.getString(R.string.study_voice_listen_follow, q.say)) {
                main.post { if (!closed) listen() }
            }
        } else {
            StudyVoice.speak(service, service.getString(R.string.study_voice_follow)) {
                main.post { if (!closed) listen() }
            }
        }
    }

    private fun listen() {
        if (closed) return
        stopSpeech()
        val generation = listenGeneration
        showCue(Cue.SPEAK)
        status.text = service.getString(R.string.study_mic_ready)
        status.setTextColor(Color.rgb(130, 220, 160))
        status.visibility = View.VISIBLE
        // Beep first, then let the microphone settle so the cue cannot become the answer.
        StudyCue.start()
        main.postDelayed({
            if (!closed && generation == listenGeneration) startRecognizer(generation)
        }, 350)
    }

    private fun startRecognizer(generation: Int) {
        if (closed || generation != listenGeneration) return
        val component = ComponentName(service, AerialRecognitionService::class.java)
        val recognizer = SpeechRecognizer.createSpeechRecognizer(service, component)
        speech = recognizer
        listening = true
        recognizer.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: android.os.Bundle?) {
                if (closed || generation != listenGeneration) return
                showCue(Cue.SPEAK)
                status.text = service.getString(R.string.study_mic_ready)
                status.setTextColor(Color.rgb(130, 220, 160))
                status.visibility = View.VISIBLE
            }

            override fun onBeginningOfSpeech() {
                if (closed || generation != listenGeneration) return
                showCue(Cue.SPEAK)
                status.text = service.getString(R.string.study_mic_listening)
                status.setTextColor(Color.rgb(92, 164, 255))
                status.visibility = View.VISIBLE
            }

            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}

            override fun onEndOfSpeech() {
                if (closed || generation != listenGeneration) return
                showCue(Cue.PROCESS)
                status.text = service.getString(R.string.study_mic_processing)
                status.setTextColor(Color.LTGRAY)
                status.visibility = View.VISIBLE
                StudyCue.end()
            }

            override fun onError(error: Int) {
                if (closed || generation != listenGeneration) return
                listening = false
                when (error) {
                    SpeechRecognizer.ERROR_NO_MATCH,
                    SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
                    SpeechRecognizer.ERROR_CLIENT -> retry("no speech")
                    else -> retry("recognizer $error")
                }
            }

            override fun onResults(results: android.os.Bundle?) {
                if (closed || generation != listenGeneration) return
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
        showCue(Cue.PROCESS)
        status.text = service.getString(R.string.study_recognizing)
        status.setTextColor(Color.LTGRAY)
        status.visibility = View.VISIBLE
        main.removeCallbacks(timeout)
        io.execute {
            val answer = runCatching { StudyClient.answer(s.id, q.id, transcript) }
            main.post {
                if (closed) return@post
                answer.onSuccess { a ->
                    if (a.retry) {
                        // Near pronunciation miss: repeat the model word and listen to the same card.
                        showCue(Cue.SPEAK)
                        announce(R.string.study_voice_retry) {
                            main.postDelayed({ if (!closed) showQuestion() }, 300)
                        }
                        return@post
                    }
                    if (a.restart || !a.correct) {
                        showCue(Cue.CROSS)
                        announce(R.string.study_voice_wrong) {
                            main.postDelayed({ if (!closed) startSession() }, 500)
                        }
                        return@post
                    }
                    index = a.progress
                    if (a.finished || index >= s.questions.size) {
                        main.removeCallbacks(timeout)
                        showCue(Cue.CHECK)
                        announce(R.string.study_voice_passed) { main.postDelayed(pass, 600) }
                    } else {
                        showCue(Cue.CHECK)
                        announce(R.string.study_voice_right) {
                            main.postDelayed({ if (!closed) showQuestion() }, 300)
                        }
                    }
                }.onFailure {
                    Log.w(TAG, "answer failed", it)
                    showCue(Cue.CROSS)
                    announce(R.string.study_voice_error) { retryLater() }
                }
            }
        }
    }

    /** Show text and speak the same reminder; only continue after the voice has finished. */
    private fun announce(res: Int, then: (() -> Unit)? = null) {
        val text = service.getString(res)
        status.setTextColor(Color.WHITE)
        status.text = text
        status.visibility = View.VISIBLE
        StudyVoice.speak(service, text) {
            main.post { if (!closed) then?.invoke() }
        }
    }

    private fun retry(reason: String) {
        if (closed) return
        stopSpeech()
        attempt++
        DiagLog.i("study: retry $attempt ($reason)")
        val noSpeech = reason == "no speech" || reason == "empty"
        showCue(if (noSpeech) Cue.SPEAK else Cue.CROSS)
        val voice = if (noSpeech) R.string.study_voice_no_speech else R.string.study_voice_error
        announce(voice) {
            if (attempt <= 3) main.postDelayed({ if (!closed) listen() }, 500)
            else retryLater()
        }
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
        hideCue()
        StudyVoice.stop()
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
        listenGeneration++
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
