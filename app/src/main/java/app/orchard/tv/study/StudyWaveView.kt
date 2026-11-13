package app.orchard.tv.study

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.view.View
import kotlin.math.sin

/** Small animated bars used while the TV is listening. The phase animates; the level is live RMS. */
class StudyWaveView(context: Context) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = StudyStyle.Focus }
    private val bars = 9
    private val rect = RectF()
    private var phase = 0f
    private var level = 0f
    private var active = false
    private val animator = ValueAnimator.ofFloat(0f, (Math.PI * 2).toFloat()).apply {
        duration = 2_700
        repeatCount = ValueAnimator.INFINITE
        addUpdateListener { phase = it.animatedValue as Float; invalidate() }
    }

    fun setActive(value: Boolean) {
        if (active == value) return
        active = value
        if (value) animator.start() else { animator.cancel(); phase = 0f }
        invalidate()
    }

    fun setLevel(value: Float) {
        level = value.coerceIn(0f, 1f)
    }

    override fun onDetachedFromWindow() {
        animator.cancel()
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (!active && level <= 0f) return
        val w = width.toFloat()
        val h = height.toFloat()
        val gap = w / (bars * 2f)
        val barWidth = gap * 0.78f
        val mid = h / 2f
        for (i in 0 until bars) {
            val wave = (sin(phase + i * 0.65f) * 0.5f + 0.5f)
            val shape = 0.18f + 0.72f * wave
            val half = (h * 0.5f) * (if (level > 0.02f) (0.30f + 0.70f * level) else 0.62f) * shape
            val x = gap + i * (w / bars)
            rect.set(x, mid - half, x + barWidth, mid + half)
            canvas.drawRoundRect(rect, barWidth / 2f, barWidth / 2f, paint)
        }
    }
}
