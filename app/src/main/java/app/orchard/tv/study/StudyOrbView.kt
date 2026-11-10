package app.orchard.tv.study

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View

/** Flat dark microphone disc: a solid fill and a thin neutral rim. */
class StudyOrbView(context: Context) : View(context) {
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rim = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 2f * resources.displayMetrics.density
        color = Color.rgb(184, 193, 204)
    }
    private var solidMode = false
    private var solidColor = Color.rgb(34, 38, 43)

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
        fill.color = if (solidMode) solidColor else Color.rgb(34, 38, 43)
        val cx = width / 2f
        val cy = height / 2f
        val r = minOf(width, height) / 2f
        canvas.drawCircle(cx, cy, r - rim.strokeWidth / 2f, fill)
        canvas.drawCircle(cx, cy, r - rim.strokeWidth / 2f, rim)
    }
}
