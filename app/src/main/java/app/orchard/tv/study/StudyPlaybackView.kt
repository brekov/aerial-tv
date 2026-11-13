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

/**
 * Nine rising rounded bars, laid out on the same width as the recording wave.
 * The first is effectively a dot; the last matches the tallest recording bar.
 */
class StudyPlaybackView(context: Context) : View(context) {
    private val bar = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        color = StudyStyle.Focus
    }
    private val dot = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = StudyStyle.Focus
    }
    private val rect = RectF()
    private val curve = Path()
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
        val count = 9
        val width = width.toFloat()
        val height = height.toFloat()
        // Match StudyWaveView's horizontal span: centers at w/18 .. 17w/18, bar w/23.
        val firstX = width / 18f
        val lastX = width * 17f / 18f
        val step = (lastX - firstX) / (count - 1)
        val barWidth = width / 23f
        val maxHeight = height * 0.56f
        val centerY = height / 2f
        for (i in 0 until count) {
            val x = firstX + i * step
            val linear = i / (count - 1f)
            val target = barWidth + (maxHeight - barWidth) * linear
            // A small travelling pulse, left to right, keeps all nine visible.
            val local = (phase + i * 0.075f) % 1f
            val pulse = 0.94f + 0.06f * sin((local * Math.PI * 2).toFloat())
            val h = target * pulse
            val alpha = (205 + 50 * sin((local * Math.PI * 2 + 0.7).toFloat())).toInt().coerceIn(150, 255)
            bar.alpha = alpha
            bar.strokeWidth = barWidth
            if (i == 0) {
                dot.alpha = alpha
                canvas.drawCircle(x, centerY, barWidth / 2f, dot)
            } else {
                val bend = barWidth * 0.38f
                curve.reset()
                curve.moveTo(x, centerY + h / 2f)
                curve.quadTo(x + bend, centerY, x, centerY - h / 2f)
                canvas.drawPath(curve, bar)
            }
        }
    }
}
