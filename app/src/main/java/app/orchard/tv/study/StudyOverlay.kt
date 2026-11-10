package app.orchard.tv.study

import android.accessibilityservice.AccessibilityService
import android.animation.ValueAnimator
import android.content.ComponentName
import android.content.res.ColorStateList
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Outline
import android.graphics.PixelFormat
import android.graphics.RenderEffect
import android.graphics.Shader
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
import android.util.TypedValue
import android.view.Display
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewOutlineProvider
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
    private lateinit var wave: StudyWaveView
    private lateinit var playback: StudyPlaybackView
    private lateinit var sadStar: ImageView
    private var cueAnimator: ValueAnimator? = null
    private enum class Cue { READY, LISTEN, SPEAK, PROCESS, CHECK, CROSS }
    private var speech: SpeechRecognizer? = null
    private var session: StudyClient.Session? = null
    private var index = 0
    private var listening = false
    private var listenGeneration = 0
    private var closed = false
    private var attempt = 0
    private var oldVolume = -1
    private var oldMute = false
    private var wasPlaying = false
    private var hasFocus = false

    private val timeout = Runnable { if (!closed) retry("timeout") }
    private val pass = Runnable { finish(true) }
    private val nextStep = Runnable {
        if (!closed) showQuestion()
    }

    internal fun show() {
        if (active) return
        if (!StudySettings.enabled) return
        active = true
        closed = false
        index = 0
        attempt = 0
        captureBackdropThenShow()
    }

    private fun captureBackdropThenShow() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            showBuilt(null)
            return
        }
        val requested = runCatching {
            service.takeScreenshot(
                Display.DEFAULT_DISPLAY,
                service.mainExecutor,
                object : AccessibilityService.TakeScreenshotCallback {
                    override fun onSuccess(result: AccessibilityService.ScreenshotResult) {
                        val bitmap = runCatching {
                            Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)
                                ?.copy(Bitmap.Config.ARGB_8888, false)
                        }.getOrNull()
                        runCatching { result.hardwareBuffer.close() }
                        main.post { if (!closed) showBuilt(bitmap) }
                    }

                    override fun onFailure(errorCode: Int) {
                        Log.w(TAG, "study backdrop screenshot failed: $errorCode")
                        main.post { if (!closed) showBuilt(null) }
                    }
                },
            )
        }
        if (requested.isFailure) {
            Log.w(TAG, "study backdrop screenshot unavailable", requested.exceptionOrNull())
            showBuilt(null)
        }
    }

    private fun showBuilt(backdrop: Bitmap?) {
        if (closed) return
        build(backdrop)
        pauseAudio()
        HomeGuardService.studyOverlayChanged()
        startSession()
        DiagLog.i("study: overlay shown")
    }

    private fun build(backdrop: Bitmap?) {
        root = FrameLayout(service).apply {
            setBackgroundColor(Color.TRANSPARENT)
            isFocusable = true
            isFocusableInTouchMode = true
            setOnKeyListener { _, keyCode, _ ->
                keyCode != KeyEvent.KEYCODE_POWER &&
                    keyCode !in setOf(
                        KeyEvent.KEYCODE_DPAD_UP,
                        KeyEvent.KEYCODE_DPAD_DOWN,
                        KeyEvent.KEYCODE_DPAD_LEFT,
                        KeyEvent.KEYCODE_DPAD_RIGHT,
                        KeyEvent.KEYCODE_DPAD_CENTER,
                        KeyEvent.KEYCODE_ENTER,
                    )
            }
        }
        val density = service.resources.displayMetrics.density
        val screenWidth = service.resources.displayMetrics.widthPixels

        // Aerial's glass is frosted wallpaper. An accessibility overlay cannot share that bitmap,
        // so take the live frame underneath once, blur it, and use it as the glass backdrop.
        if (backdrop != null) {
            val background = ImageView(service).apply {
                scaleType = ImageView.ScaleType.CENTER_CROP
                setImageBitmap(backdrop)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    setRenderEffect(
                        RenderEffect.createBlurEffect(
                            32f * density,
                            32f * density,
                            Shader.TileMode.CLAMP,
                        ),
                    )
                }
            }
            root.addView(background, FrameLayout.LayoutParams(-1, -1))
            root.addView(View(service).apply {
                setBackground(GradientDrawable(
                    GradientDrawable.Orientation.TL_BR,
                    intArrayOf(Color.argb(185, 9, 28, 62), Color.argb(210, 3, 10, 26)),
                ))
            }, FrameLayout.LayoutParams(-1, -1))
        } else {
            root.addView(View(service).apply {
                setBackground(GradientDrawable(
                    GradientDrawable.Orientation.TL_BR,
                    intArrayOf(Color.argb(240, 9, 28, 62), Color.argb(250, 3, 10, 26)),
                ))
            }, FrameLayout.LayoutParams(-1, -1))
        }

        val column = LinearLayout(service).apply { orientation = LinearLayout.VERTICAL }

        // One full-width progress line at the very top. The split content starts below it.
        progress = ProgressBar(service, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = false
            max = StudySettings.QUESTIONS
            progressTintList = ColorStateList.valueOf(Color.rgb(47, 123, 255))
            progressBackgroundTintList = ColorStateList.valueOf(Color.argb(90, 255, 255, 255))
            minimumHeight = (5 * density).toInt().coerceAtLeast(3)
        }
        column.addView(progress, LinearLayout.LayoutParams(-1, (5 * density).toInt().coerceAtLeast(3)))

        val content = LinearLayout(service).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding((14 * density).toInt(), (12 * density).toInt(), (14 * density).toInt(), (12 * density).toInt())
        }

        // Frosted-glass hint panel: title, hint/result, and the centered cue icon.
        val left = LinearLayout(service).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((28 * density).toInt(), (22 * density).toInt(), (20 * density).toInt(), (22 * density).toInt())
            background = GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                intArrayOf(Color.argb(238, 40, 105, 200), Color.argb(220, 5, 20, 48)),
            ).apply {
                cornerRadius = 30 * density
                setStroke((1 * density).toInt().coerceAtLeast(1), Color.argb(80, 125, 200, 255))
            }
        }
        val badge = ImageView(service).apply {
            setImageResource(R.drawable.study_cue_speaker)
            setColorFilter(Color.WHITE)
            setPadding((8 * density).toInt(), (8 * density).toInt(), (8 * density).toInt(), (8 * density).toInt())
            background = GradientDrawable().apply {
                cornerRadius = 13 * density
                setColor(Color.argb(180, 45, 118, 220))
                setStroke((1 * density).toInt().coerceAtLeast(1), Color.argb(110, 180, 220, 255))
            }
        }
        left.addView(badge, LinearLayout.LayoutParams((38 * density).toInt(), (38 * density).toInt()))
        title = text(18f, Color.WHITE, Typeface.BOLD).apply {
            text = service.getString(R.string.study_title)
            maxLines = 1
            setSingleLine()
            ellipsize = TextUtils.TruncateAt.END
            setPadding(0, (12 * density).toInt(), 0, 0)
        }
        status = text(17f, Color.rgb(130, 230, 160), Typeface.BOLD).apply {
            maxWidth = (screenWidth * 0.24f).toInt()
            maxLines = 2
            ellipsize = TextUtils.TruncateAt.END
            gravity = Gravity.CENTER_HORIZONTAL
            textAlignment = View.TEXT_ALIGNMENT_CENTER
            setPadding(0, (6 * density).toInt(), 0, 0)
            visibility = View.INVISIBLE
        }
        left.addView(title, LinearLayout.LayoutParams(-1, -2))

        val cueSize = (84 * density).toInt()
        cue = ImageView(service).apply {
            setPadding((10 * density).toInt(), (10 * density).toInt(), (10 * density).toInt(), (10 * density).toInt())
            visibility = View.INVISIBLE
            contentDescription = "Study cue"
        }
        wave = StudyWaveView(service)
        playback = StudyPlaybackView(service)
        val cueHolder = FrameLayout(service).apply {
            addView(wave, FrameLayout.LayoutParams(-1, (96 * density).toInt(), Gravity.TOP).apply {
                leftMargin = (10 * density).toInt()
                rightMargin = (10 * density).toInt()
            })
            addView(playback, FrameLayout.LayoutParams(-1, (96 * density).toInt(), Gravity.TOP))
            addView(cue, FrameLayout.LayoutParams(cueSize, cueSize, Gravity.CENTER))
        }
        val centerBlock = LinearLayout(service).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
        }
        centerBlock.addView(cueHolder, LinearLayout.LayoutParams(-1, (100 * density).toInt()))
        centerBlock.addView(status, LinearLayout.LayoutParams(-1, -2))
        left.addView(centerBlock, LinearLayout.LayoutParams(-1, 0, 1f))
        sadStar = ImageView(service).apply {
            setImageResource(R.drawable.study_cue_star_sad)
            visibility = View.GONE
            contentDescription = "Sad star"
        }
        left.addView(sadStar, LinearLayout.LayoutParams((56 * density).toInt(), (56 * density).toInt()).apply { gravity = Gravity.CENTER_HORIZONTAL })

        val imageStage = FrameLayout(service).apply {
            setPadding((14 * density).toInt(), (14 * density).toInt(), (14 * density).toInt(), (14 * density).toInt())
            // No white card and no pink border: the image sits directly on the same frosted glass.
            background = GradientDrawable().apply {
                cornerRadius = 30 * density
                setColor(Color.TRANSPARENT)
            }
        }
        image = ImageView(service).apply {
            scaleType = ImageView.ScaleType.FIT_CENTER
            setBackgroundColor(Color.TRANSPARENT)
        }
        imageStage.addView(image, FrameLayout.LayoutParams(-1, -1))

        content.addView(left, LinearLayout.LayoutParams(0, -1, 0.30f).apply { rightMargin = (7 * density).toInt() })
        content.addView(imageStage, LinearLayout.LayoutParams(0, -1, 0.70f))
        column.addView(content, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(column, FrameLayout.LayoutParams(-1, -1))

        // Aerial pages use a translucent dark glass. Accessibility overlays cannot call Compose's
        // liquidGlass, so use a translucent gradient with a lit rim and try native blur behind.
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
            dimAmount = 0.10f
            title = "Aerial study"
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            lp.flags = lp.flags or WindowManager.LayoutParams.FLAG_BLUR_BEHIND
            lp.blurBehindRadius = (28 * density).toInt()
        }
        wm.addView(root, lp)
        root.requestFocus()
    }

    private fun scheduleNext() {
        if (closed) return
        main.removeCallbacks(nextStep)
        main.postDelayed(nextStep, 1_600)
    }

    private fun text(size: Float, color: Int, style: Int) = TextView(service).apply {
        textSize = size
        setTextColor(color)
        typeface = Typeface.create(Typeface.DEFAULT, style)
    }

    /** Big, animated non-text cue so a child can see whether to listen, speak or wait. */
    private fun showCue(mode: Cue) {
        if (!::cue.isInitialized || closed) return
        cue.setImageResource(
            when (mode) {
                Cue.READY -> R.drawable.study_cue_mic
                Cue.LISTEN -> R.drawable.study_cue_speaker
                Cue.SPEAK -> R.drawable.study_cue_mic
                Cue.PROCESS -> R.drawable.study_cue_processing
                Cue.CHECK -> R.drawable.study_cue_check
                Cue.CROSS -> R.drawable.study_cue_cross
            }
        )
        val result = mode == Cue.CHECK || mode == Cue.CROSS
        cue.visibility = if (result) View.VISIBLE else View.INVISIBLE
        cue.colorFilter = when (mode) {
            Cue.CHECK -> android.graphics.PorterDuffColorFilter(Color.rgb(48, 209, 88), android.graphics.PorterDuff.Mode.SRC_IN)
            Cue.CROSS -> android.graphics.PorterDuffColorFilter(Color.rgb(255, 69, 58), android.graphics.PorterDuff.Mode.SRC_IN)
            else -> null
        }
        if (::sadStar.isInitialized) sadStar.visibility = if (mode == Cue.CROSS) View.VISIBLE else View.GONE
        val showPlayback = mode == Cue.LISTEN
        playback.setActive(showPlayback)
        val showWave = mode == Cue.READY || mode == Cue.SPEAK
        wave.setActive(showWave)
        wave.visibility = if (showWave) View.VISIBLE else View.INVISIBLE
        cueAnimator?.cancel()
        cue.rotation = 0f
        cue.scaleX = 1f
        cue.scaleY = 1f
        cue.alpha = 1f
        cueAnimator = if (mode == Cue.CHECK || mode == Cue.CROSS) {
            ValueAnimator.ofFloat(0.7f, 1.1f).apply {
                duration = 660
                addUpdateListener {
                    val scale = it.animatedValue as Float
                    cue.scaleX = scale
                    cue.scaleY = scale
                }
            }.also { it.start() }
        } else {
            null
        }
    }

    private fun hideCue() {
        if (!::cue.isInitialized) return
        cueAnimator?.cancel()
        cueAnimator = null
        cue.visibility = View.INVISIBLE
        if (::playback.isInitialized) playback.setActive(false)
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
        main.removeCallbacks(nextStep)
        wave.setActive(false)
        playback.setActive(false)
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
        showCue(Cue.READY)
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
                showCue(Cue.READY)
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
                        showCue(Cue.READY)
                        announce(R.string.study_voice_retry) {
                            main.postDelayed({ if (!closed) showQuestion() }, 300)
                        }
                        return@post
                    }
                    if (a.restart || !a.correct) {
                        showCue(Cue.CROSS)
                        val wrong = service.getString(R.string.study_wrong_hint)
                        announce(R.string.study_voice_wrong, wrong) {
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
                        val display = service.getString(R.string.study_right) + " · " +
                            service.getString(R.string.study_score, a.score) + "\n" +
                            service.getString(R.string.study_next_auto)
                        announce(R.string.study_voice_right, display, { scheduleNext() })
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
    private fun announce(res: Int, display: String? = null, then: (() -> Unit)? = null) {
        val text = service.getString(res)
        status.setTextColor(Color.WHITE)
        status.text = display ?: text
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
        showCue(if (noSpeech) Cue.READY else Cue.CROSS)
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
        wave.setActive(false)
        playback.setActive(false)
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

    private fun dispatchMediaKey(keyCode: Int) {
        audio.dispatchMediaKeyEvent(android.view.KeyEvent(android.view.KeyEvent.ACTION_DOWN, keyCode))
        audio.dispatchMediaKeyEvent(android.view.KeyEvent(android.view.KeyEvent.ACTION_UP, keyCode))
    }

    private fun pauseAudio() {
        runCatching {
            oldVolume = audio.getStreamVolume(AudioManager.STREAM_MUSIC)
            oldMute = Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && audio.isStreamMute(AudioManager.STREAM_MUSIC)
            // Only send PAUSE if something is actually playing; resuming a video the user had
            // already paused would be worse than leaving it alone.
            wasPlaying = audio.isMusicActive()
            if (wasPlaying) dispatchMediaKey(android.view.KeyEvent.KEYCODE_MEDIA_PAUSE)
            @Suppress("DEPRECATION")
            hasFocus = audio.requestAudioFocus(null, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT) ==
                AudioManager.AUDIOFOCUS_REQUEST_GRANTED
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, 0)
        }
    }

    private fun restoreAudio() {
        val resume = wasPlaying
        wasPlaying = false
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
        if (resume) {
            // Some players resume themselves when focus is released; give them a moment, then
            // send PLAY only if nothing is playing. The key is routed to the active media session.
            main.postDelayed({
                if (!audio.isMusicActive()) dispatchMediaKey(android.view.KeyEvent.KEYCODE_MEDIA_PLAY)
            }, 350)
        }
    }

    fun dismissFromOutside() {
        if (!closed) finish(false)
    }
}
