package app.orchard.tv.study

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.View
import kotlin.math.sin

/** Speaker + expanding arcs for the model-pronunciation playback state (no circular icon). */
class StudyPlaybackView(context: Context) : View(context) {
    private val speaker = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(225, 248, 255)
        style = Paint.Style.FILL
    }
    private val arc = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        color = Color.rgb(96, 218, 255)
    }
    private val body = RectF()
    private val wedge = Path()
    private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 2_400
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
        val cx = width * 0.40f
        val cy = height / 2f
        val unit = minOf(width, height) / 100f * 1.1f
        // Speaker body and cone.
        body.set(cx - 20 * unit, cy - 9 * unit, cx - 5 * unit, cy + 9 * unit)
        canvas.drawRoundRect(body, 3 * unit, 3 * unit, speaker)
        wedge.reset()
        wedge.moveTo(cx - 6 * unit, cy - 9 * unit)
        wedge.lineTo(cx + 14 * unit, cy - 24 * unit)
        wedge.lineTo(cx + 14 * unit, cy + 24 * unit)
        wedge.lineTo(cx - 6 * unit, cy + 9 * unit)
        wedge.close()
        canvas.drawPath(wedge, speaker)
        // Three arcs expanding to the right, offset in phase.
        val phase = (animator.animatedValue as? Float) ?: 0f
        arc.strokeWidth = 3.4f * unit
        for (i in 0..2) {
            val p = (phase + i / 3f) % 1f
            val radius = (18f + p * 28f) * unit
            arc.alpha = (190 * (1f - p)).toInt().coerceIn(20, 190)
            canvas.drawArc(
                RectF(cx + 16 * unit - radius, cy - radius, cx + 16 * unit + radius, cy + radius),
                -55f, 110f, false, arc,
            )
        }
        // A small level pulse under the speaker.
        val pulse = (sin(phase * Math.PI * 2).toFloat() * 0.5f + 0.5f)
        arc.alpha = 150
        arc.strokeWidth = 3f * unit
        canvas.drawLine(
            cx + 22 * unit, cy + 29 * unit,
            cx + 22 * unit + (32f + 20f * pulse) * unit, cy + 29 * unit, arc,
        )
    }
}
