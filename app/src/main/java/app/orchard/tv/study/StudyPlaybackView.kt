package app.orchard.tv.study

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.view.View
import kotlin.math.sin

/** Concentric short sound arcs that sweep outward from left to right for playback. */
class StudyPlaybackView(context: Context) : View(context) {
    private val arc = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        color = Color.rgb(105, 224, 255)
    }
    private val rect = RectF()
    private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 2_200
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
        val unit = minOf(width, height) / 100f
        val cx = width * 0.18f
        val cy = height / 2f
        val count = 6
        for (i in 0 until count) {
            val local = (phase + i / count.toFloat()) % 1f
            // Each arc grows then fades; the offset makes them appear in sequence.
            val radius = (22f + i * 11f + local * 5f) * unit
            val alpha = (220f * sin(local * Math.PI).toFloat()).toInt().coerceIn(18, 220)
            arc.alpha = alpha
            arc.strokeWidth = (5.2f + i * 0.55f) * unit
            rect.set(cx - radius, cy - radius, cx + radius, cy + radius)
            canvas.drawArc(rect, -39f, 78f, false, arc)
        }
    }
}
