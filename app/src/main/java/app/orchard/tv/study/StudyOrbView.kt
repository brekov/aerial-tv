package app.orchard.tv.study

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.view.View

/** Bright product-style microphone orb with halo rings and right-side sound ticks. */
class StudyOrbView(context: Context) : View(context) {
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rim = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = Color.argb(225, 235, 252, 255)
    }
    private val halo = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = Color.argb(58, 92, 190, 255)
    }
    private val shine = Paint(Paint.ANTI_ALIAS_FLAG)
    private val tick = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        color = Color.argb(235, 126, 231, 255)
    }
    private var solidMode = false
    private var solidColor = Color.rgb(48, 209, 88)
    private var density = resources.displayMetrics.density

    fun solid(color: Int) {
        solidMode = true
        solidColor = color
        invalidate()
    }

    fun blue() {
        solidMode = false
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        density = resources.displayMetrics.density
        val cx = width / 2f
        val cy = height / 2f
        val r = minOf(width, height) / 2f
        val mainR = r * 0.79f

        // Two soft concentric halos.
        halo.strokeWidth = 1.4f * density
        canvas.drawCircle(cx, cy, mainR + 8f * density, halo)
        halo.color = Color.argb(34, 92, 190, 255)
        canvas.drawCircle(cx, cy, mainR + 15f * density, halo)
        halo.color = Color.argb(58, 92, 190, 255)

        fill.shader = if (solidMode) {
            null
        } else {
            RadialGradient(
                cx - mainR * 0.32f, cy - mainR * 0.38f, mainR * 1.32f,
                intArrayOf(
                    Color.rgb(185, 247, 255),
                    Color.rgb(62, 170, 255),
                    Color.rgb(20, 101, 220),
                    Color.rgb(8, 40, 112),
                ),
                floatArrayOf(0f, 0.30f, 0.68f, 1f),
                Shader.TileMode.CLAMP,
            )
        }
        if (solidMode) fill.color = solidColor
        canvas.drawCircle(cx, cy, mainR, fill)

        // Soft highlight in the upper-left, like the reference render.
        if (!solidMode) {
            shine.shader = RadialGradient(
                cx - mainR * 0.28f, cy - mainR * 0.34f, mainR * 0.9f,
                intArrayOf(Color.argb(92, 255, 255, 255), Color.TRANSPARENT),
                floatArrayOf(0f, 1f), Shader.TileMode.CLAMP,
            )
            shine.style = Paint.Style.FILL
            canvas.drawCircle(cx, cy, mainR, shine)
            drawTicks(canvas, cx, cy, mainR)
        }

        rim.strokeWidth = 1.8f * density
        canvas.drawCircle(cx, cy, mainR, rim)
    }

    private fun drawTicks(canvas: Canvas, cx: Float, cy: Float, mainR: Float) {
        tick.strokeWidth = 3.2f * density
        val d = 1f / kotlin.math.sqrt(2f)
        val start = mainR + 8f * density
        val end = mainR + 20f * density
        canvas.drawLine(
            cx + start * 0.72f, cy - start * 0.72f,
            cx + end * 0.72f, cy - end * 0.72f, tick,
        )
        val start2 = mainR + 5f * density
        val end2 = mainR + 13f * density
        canvas.drawLine(
            cx + start2 * 0.98f, cy - start2 * 0.18f,
            cx + end2 * 0.98f, cy - end2 * 0.18f, tick,
        )
        // Keep d referenced so the intent stays clear for diagonal ticks.
        if (d < 0f) return
    }
}
