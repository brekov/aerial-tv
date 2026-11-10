package app.orchard.tv.study

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.view.View
import kotlin.math.sin

/** Rising rounded bars, gently bent into an arc, for the model-audio playback state. */
class StudyPlaybackView(context: Context) : View(context) {
    private val bar = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.rgb(91, 200, 255)
    }
    private val rect = RectF()
    private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 1_900
        repeatCount = ValueAnimator.INFINITE
        addUpdateListener { invalidate() }
    }

    fun setActive(active: Boolean) {
        if (active && !animator.isStarted) animator.start()
        if (!active) animator.cancel()
        visibility = if (active) VISIBLE else INVISIBLE
        invalidate()
    }

    override fun onDetachedFromWindow() {
        animator.cancel()
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (visibility != VISIBLE) return
        val phase = (animator.animatedValue as? Float) ?: 0f
        val count = 6
        val startX = width * 0.12f
        val endX = width * 0.88f
        val step = (endX - startX) / (count - 1)
        val barWidth = width * 0.045f
        val baseBottom = height * 0.84f
        val half = (endX - startX) / 2f
        val center = (startX + endX) / 2f
        for (i in 0 until count) {
            val x = startX + i * step
            val growth = 0.13f + i * 0.115f
            val pulse = 0.88f + 0.12f * sin((phase * Math.PI * 2 + i * 0.55).toFloat())
            val h = height * growth * pulse
            // Gentle downward bow at the center, so the row reads as a shallow arc.
            val curve = ((x - center) / half).let { it * it } * height * 0.035f
            val bottom = baseBottom + curve
            rect.set(x - barWidth / 2f, bottom - h, x + barWidth / 2f, bottom)
            bar.alpha = (210 + 45 * sin((phase * Math.PI * 2 + i * 0.8).toFloat())).toInt().coerceIn(150, 255)
            canvas.drawRoundRect(rect, barWidth / 2f, barWidth / 2f, bar)
        }
    }
}
