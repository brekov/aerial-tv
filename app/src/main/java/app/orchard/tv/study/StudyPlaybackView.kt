package app.orchard.tv.study

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.view.View

/**
 * Playback cue: a speaker followed by bars that appear one by one from left to right.
 * The bars keep a fixed height; the motion is the travelling appearance, not a vertical sine wave.
 */
class StudyPlaybackView(context: Context) : View(context) {
    private val bar = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        color = StudyStyle.Focus
    }
    private val speaker = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = StudyStyle.Focus
    }
    private val speakerLine = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        color = StudyStyle.Focus
    }
    private val rect = RectF()
    private val speakerPath = Path()
    private var phase = 0f
    private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 3_300
        repeatCount = ValueAnimator.INFINITE
        addUpdateListener { phase = it.animatedValue as Float; invalidate() }
    }

    fun setActive(active: Boolean) {
        if (active) {
            if (!animator.isStarted) animator.start()
            visibility = VISIBLE
        } else {
            animator.cancel()
            visibility = INVISIBLE
        }
        invalidate()
    }

    override fun onDetachedFromWindow() {
        animator.cancel()
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (visibility != VISIBLE) return
        val width = width.toFloat()
        val height = height.toFloat()
        if (width <= 0f || height <= 0f) return
        val centerY = height / 2f
        val glyphSize = height * 0.46f
        val left = width * 0.06f
        drawSpeaker(canvas, left, centerY, glyphSize)

        val barCount = 7
        val startX = left + glyphSize * 1.15f
        val endX = width * 0.94f
        val step = (endX - startX) / barCount
        val barWidth = (width / 34f).coerceAtLeast(width / 42f)
        bar.strokeWidth = barWidth
        val maxHeight = height * 0.58f
        for (i in 0 until barCount) {
            val local = ((phase - i * 0.075f) / 0.48f).coerceIn(0f, 1f)
            if (local <= 0f) continue
            bar.alpha = (local * 255f).toInt().coerceIn(0, 255)
            val x = startX + step * (i + 0.5f)
            val target = height * (0.20f + 0.36f * (i.toFloat() / (barCount - 1)))
            rect.set(x - barWidth / 2f, centerY - target / 2f, x + barWidth / 2f, centerY + target / 2f)
            canvas.drawRoundRect(rect, barWidth / 2f, barWidth / 2f, bar)
        }
    }

    private fun drawSpeaker(canvas: Canvas, x: Float, cy: Float, size: Float) {
        val bodyW = size * 0.20f
        val bodyH = size * 0.30f
        val coneW = size * 0.38f
        val coneH = size * 0.68f
        val bodyLeft = x
        rect.set(bodyLeft, cy - bodyH / 2f, bodyLeft + bodyW, cy + bodyH / 2f)
        canvas.drawRoundRect(rect, bodyW * 0.22f, bodyW * 0.22f, speaker)
        speakerPath.reset()
        speakerPath.moveTo(bodyLeft + bodyW, cy - coneH * 0.30f)
        speakerPath.lineTo(bodyLeft + bodyW + coneW, cy - coneH / 2f)
        speakerPath.lineTo(bodyLeft + bodyW + coneW, cy + coneH / 2f)
        speakerPath.lineTo(bodyLeft + bodyW, cy + coneH * 0.30f)
        speakerPath.close()
        canvas.drawPath(speakerPath, speaker)
        speakerLine.strokeWidth = (size * 0.055f).coerceAtLeast(1f)
        val arcLeft = bodyLeft + bodyW + coneW * 0.18f
        val arcSize = size * 0.43f
        for (i in 0 until 2) {
            val inset = i * size * 0.12f
            rect.set(arcLeft - inset, cy - arcSize / 2f - inset, arcLeft + arcSize - inset, cy + arcSize / 2f + inset)
            canvas.drawArc(rect, -50f, 100f, false, speakerLine)
        }
    }
}
