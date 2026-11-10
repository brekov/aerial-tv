package app.orchard.tv.study

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.view.View

/** A guaranteed-circular blue/green/red orb behind the cue glyph. */
class StudyOrbView(context: Context) : View(context) {
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rim = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = Color.argb(210, 255, 255, 255)
    }
    private val glow = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(42, 74, 170, 255) }
    private val shine = Paint(Paint.ANTI_ALIAS_FLAG)
    private var topColor = Color.rgb(105, 201, 255)
    private var bottomColor = Color.rgb(8, 46, 132)

    fun solid(color: Int) {
        topColor = color
        bottomColor = color
        invalidate()
    }

    fun blue() {
        topColor = Color.rgb(62, 142, 255)
        bottomColor = Color.rgb(10, 42, 110)
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val r = minOf(width, height) / 2f
        fill.shader = LinearGradient(0f, 0f, width.toFloat(), height.toFloat(), topColor, bottomColor, Shader.TileMode.CLAMP)
        rim.strokeWidth = (2 * resources.displayMetrics.density).coerceAtLeast(2f)
        canvas.drawCircle(width / 2f, height / 2f, r - rim.strokeWidth, glow)
        canvas.drawCircle(width / 2f, height / 2f, r - rim.strokeWidth / 2f, fill)
        shine.shader = RadialGradient(
            width * 0.34f, height * 0.28f, r * 0.72f,
            intArrayOf(Color.argb(150, 255, 255, 255), Color.TRANSPARENT),
            floatArrayOf(0f, 1f), Shader.TileMode.CLAMP,
        )
        shine.style = Paint.Style.FILL
        canvas.drawCircle(width * 0.34f, height * 0.28f, r * 0.60f, shine)
        canvas.drawCircle(width / 2f, height / 2f, r - rim.strokeWidth / 2f, rim)
    }
}
