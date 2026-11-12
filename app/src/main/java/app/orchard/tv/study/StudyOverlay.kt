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
    private lateinit var leftCard: LinearLayout
    private lateinit var centerBlock: LinearLayout
    private lateinit var wave: StudyWaveView
    private lateinit var playback: StudyPlaybackView
    private var cueAnimator: ValueAnimator? = null
    private enum class Cue { READY, LISTEN, SPEAK, PROCESS, CHECK, CROSS }
    private var speech: SpeechRecognizer? = null
    private var repeatSession: StudyClient.RepeatSession? = null
    private var transition: FrameLayout? = null
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
        if (!closed) showRepeatCard()
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
            background.alpha = 0.65f
            root.addView(background, FrameLayout.LayoutParams(-1, -1))
            root.addView(View(service).apply {
                alpha = 0.65f
                setBackground(GradientDrawable(
                    GradientDrawable.Orientation.TL_BR,
                    intArrayOf(Color.argb(185, 9, 28, 62), Color.argb(210, 3, 10, 26)),
                ))
            }, FrameLayout.LayoutParams(-1, -1))
        } else {
            root.addView(View(service).apply {
                setBackground(GradientDrawable(
                    GradientDrawable.Orientation.TL_BR,
                    intArrayOf(Color.argb(166, 9, 28, 62), Color.argb(170, 3, 10, 26)),
                ))
            }, FrameLayout.LayoutParams(-1, -1))
        }

        val column = LinearLayout(service).apply { orientation = LinearLayout.VERTICAL }

        // One full-width progress line at the very top. The split content starts below it.
        progress = ProgressBar(service, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = false
            max = 3
            progressTintList = ColorStateList.valueOf(Color.rgb(47, 123, 255))
            progressBackgroundTintList = ColorStateList.valueOf(Color.argb(90, 255, 255, 255))
            minimumHeight = (5 * density).toInt().coerceAtLeast(3)
        }
        column.addView(progress, LinearLayout.LayoutParams(-1, (5 * density).toInt().coerceAtLeast(3)))

        val content = LinearLayout(service).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding((14 * density).toInt(), (12 * density).toInt(), (14 * density).toInt(), (12 * density).toInt())
        }

        // Frosted-glass hint panel: title, hint/result, and the centered cue icon.
        leftCard = LinearLayout(service).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((22 * density).toInt(), (22 * density).toInt(), (22 * density).toInt(), (22 * density).toInt())
            background = GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                intArrayOf(Color.argb(238, 40, 105, 200), Color.argb(220, 5, 20, 48)),
            ).apply {
                cornerRadius = 30 * density
                setStroke((1 * density).toInt().coerceAtLeast(1), Color.argb(80, 125, 200, 255))
            }
        }
        title = text(14f, Color.WHITE, Typeface.BOLD).apply {
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
        leftCard.addView(title, LinearLayout.LayoutParams(-1, -2))

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
            addView(playback, FrameLayout.LayoutParams(-1, (96 * density).toInt(), Gravity.TOP).apply {
                leftMargin = (10 * density).toInt()
                rightMargin = (10 * density).toInt()
            })
            addView(cue, FrameLayout.LayoutParams(cueSize, cueSize, Gravity.CENTER))
        }
        centerBlock = LinearLayout(service).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
        }
        centerBlock.addView(cueHolder, LinearLayout.LayoutParams(-1, (100 * density).toInt()))
        centerBlock.addView(status, LinearLayout.LayoutParams(-1, -2))
        leftCard.addView(centerBlock, LinearLayout.LayoutParams(-1, 0, 1f))
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
            addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> syncLeftCardHeight() }
        }
        imageStage.addView(image, FrameLayout.LayoutParams(-1, -1))

        content.addView(leftCard, LinearLayout.LayoutParams(0, -1, 0.25f).apply { rightMargin = (4 * density).toInt() })
        content.addView(imageStage, LinearLayout.LayoutParams(0, -1, 0.75f))
        column.addView(content, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(column, FrameLayout.LayoutParams(-1, -1))

        transition = FrameLayout(service).apply {
            visibility = View.GONE
            alpha = 0f
            setBackground(GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                intArrayOf(Color.argb(230, 8, 25, 55), Color.argb(240, 2, 9, 24)),
            ))
            addView(text(34f, Color.WHITE, Typeface.BOLD).apply {
                text = service.getString(R.string.study_repeat_learning)
                gravity = Gravity.CENTER
            }, FrameLayout.LayoutParams(-1, -1))
        }
        root.addView(transition, FrameLayout.LayoutParams(-1, -1))

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

    /** Match the left glass card to the actual displayed image height, including its aspect fit. */
    private fun syncLeftCardHeight() {
        if (!::leftCard.isInitialized || !::image.isInitialized) return
        val drawable = image.drawable ?: return
        val iw = drawable.intrinsicWidth
        val ih = drawable.intrinsicHeight
        val vw = image.width
        val vh = image.height
        if (iw <= 0 || ih <= 0 || vw <= 0 || vh <= 0) return
        val scale = minOf(vw.toFloat() / iw, vh.toFloat() / ih)
        val shownHeight = (ih * scale).toInt().coerceAtLeast(1)
        val params = leftCard.layoutParams
        if (params.height != shownHeight) {
            params.height = shownHeight
            leftCard.layoutParams = params
        }
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
            val result = runCatching { StudyClient.startRepeatSession() }
            main.post {
                if (closed) return@post
                result.onSuccess { s ->
                    repeatSession = s
                    index = 0
                    attempt = 0
                    if (s.cards.isEmpty()) {
                        showCue(Cue.CROSS)
                        announce(R.string.study_voice_error) { retryLater() }
                    } else {
                        transitionIntoLearning()
                    }
                }.onFailure {
                    Log.w(TAG, "repeat session failed", it)
                    showCue(Cue.CROSS)
                    announce(R.string.study_voice_error) { retryLater() }
                }
            }
        }
    }

    private fun transitionIntoLearning() {
        hideCue()
        val layer = transition ?: return showRepeatCard()
        layer.visibility = View.VISIBLE
        layer.alpha = 0f
        layer.scaleX = 0.96f
        layer.scaleY = 0.96f
        layer.animate().alpha(1f).scaleX(1f).scaleY(1f).setDuration(420).withEndAction {
            if (closed) return@withEndAction
            StudyVoice.speak(service, service.getString(R.string.study_repeat_learning)) {
                main.post {
                    if (closed) return@post
                    layer.animate().alpha(0f).setDuration(260).withEndAction {
                        layer.visibility = View.GONE
                        if (!closed) showRepeatCard()
                    }.start()
                }
            }
        }.start()
    }

    private fun showRepeatCard() {
        val s = repeatSession ?: return
        val card = s.cards.getOrNull(index) ?: return finish(true)
        stopSpeech()
        main.removeCallbacks(nextStep)
        main.removeCallbacks(timeout)
        main.postDelayed(timeout, 120_000)
        hideCue()
        centerBlock.visibility = View.VISIBLE
        progress.max = s.cards.size
        progress.progress = index + 1
        title.text = service.getString(R.string.study_repeat_learning)
        status.visibility = View.VISIBLE
        status.setTextColor(Color.WHITE)
        status.text = service.getString(R.string.study_repeat_progress, index + 1, s.cards.size)
        image.setImageBitmap(null)
        image.animate().cancel()
        image.alpha = 0f
        image.translationX = 24f * service.resources.displayMetrics.density
        if (card.imageUrl == null) {
            speakCard(card)
        } else io.execute {
            val bmp = StudyClient.loadImage(card.imageUrl)
            main.post {
                if (closed) return@post
                image.setImageBitmap(bmp)
                image.post { syncLeftCardHeight() }
                image.animate().alpha(1f).translationX(0f).setDuration(250).start()
                speakCard(card)
            }
        }
    }

    private fun speakCard(card: StudyClient.RepeatCard) {
        if (closed) return
        status.text = service.getString(R.string.study_repeat_progress, index + 1, (repeatSession?.cards?.size ?: 3))
        showCue(Cue.LISTEN)
        StudyVoice.speakSpelling(service, card.word, card.letters) {
            main.post { if (!closed) listenRepeat() }
        }
    }

    private fun listenRepeat() {
        if (closed) return
        stopSpeech()
        showCue(Cue.READY)
        status.text = service.getString(R.string.study_mic_ready)
        status.setTextColor(Color.rgb(130, 220, 160))
        status.visibility = View.VISIBLE
        startRecognizer(listenGeneration)
    }

    private fun submitRepeatAudio() {
        val s = repeatSession ?: return
        val card = s.cards.getOrNull(index) ?: return
        val wav = StudyAudioBus.take()
        if (wav == null) {
            retry("no speech")
            return
        }
        showCue(Cue.PROCESS)
        status.text = service.getString(R.string.study_recognizing)
        status.setTextColor(Color.LTGRAY)
        main.removeCallbacks(timeout)
        io.execute {
            val result = runCatching { StudyClient.submitRepeatAttempt(s.id, card.id, wav) }
            main.post {
                if (closed) return@post
                result.onSuccess { r ->
                    if (r.retry) {
                        status.text = r.feedback.ifBlank { service.getString(R.string.study_voice_retry) }
                        status.visibility = View.VISIBLE
                        showCue(Cue.READY)
                        main.postDelayed({ if (!closed) listenRepeat() }, 700)
                        return@post
                    }
                    val shown = if (r.score > 0) service.getString(R.string.study_score, r.score) else r.feedback
                    status.text = shown
                    status.setTextColor(Color.WHITE)
                    status.visibility = View.VISIBLE
                    showCue(if (r.score >= 60) Cue.CHECK else Cue.CROSS)
                    if (r.finished) {
                        index = s.cards.size
                        main.postDelayed({
                            if (!closed) {
                                announce(R.string.study_voice_passed) { main.postDelayed(pass, 500) }
                            }
                        }, 900)
                    } else {
                        index += 1
                        scheduleNext()
                    }
                }.onFailure {
                    Log.w(TAG, "repeat answer failed", it)
                    showCue(Cue.CROSS)
                    announce(R.string.study_voice_error) { retryLater() }
                }
            }
        }
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
                submitRepeatAudio()
            }

            override fun onPartialResults(partialResults: android.os.Bundle?) {}
            override fun onEvent(eventType: Int, params: android.os.Bundle?) {}
        })
        val intent = android.content.Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US")
        }
        runCatching { recognizer.startListening(intent) }.onFailure {
            Log.w(TAG, "startListening", it)
            retry("microphone")
        }
    }

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
            if (attempt <= 3) main.postDelayed({
                if (!closed) {
                    showRepeatCard()
                }
            }, 500)
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
            wasPlaying = audio.isMusicActive()
            // TTS uses the media stream. Unmute temporarily so the child can hear the
            // lesson; restore the original mute state when the overlay closes.
            if (oldMute && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_UNMUTE, 0)
            }
            @Suppress("DEPRECATION")
            hasFocus = audio.requestAudioFocus(null, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT) ==
                AudioManager.AUDIOFOCUS_REQUEST_GRANTED
            // Pause even if isMusicActive() is false: a muted player can still be moving.
            dispatchMediaKey(android.view.KeyEvent.KEYCODE_MEDIA_PAUSE)
        }
    }

    private fun restoreAudio() {
        val resume = wasPlaying
        wasPlaying = false
        runCatching {
            if (hasFocus) {
                @Suppress("DEPRECATION")
                audio.abandonAudioFocus(null)
            }
            if (oldMute && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, 0)
            }
            oldVolume = -1
            hasFocus = false
        }
        if (resume) {
            main.postDelayed({
                if (!audio.isMusicActive()) dispatchMediaKey(android.view.KeyEvent.KEYCODE_MEDIA_PLAY)
            }, 350)
        }
    }

    fun dismissFromOutside() {
        if (!closed) finish(false)
    }
}
