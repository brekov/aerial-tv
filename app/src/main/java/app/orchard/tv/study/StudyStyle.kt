package app.orchard.tv.study

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import androidx.core.content.res.ResourcesCompat
import app.orchard.tv.R

/** Native-view bridge for the Aerial/tvOS palette and typography used by the main app. */
internal object StudyStyle {
    val Label = Color.WHITE
    val Secondary = Color.argb(0x99, 0xEB, 0xEB, 0xF5)
    val Tertiary = Color.argb(0x4D, 0xEB, 0xEB, 0xF5)
    val Glass = Color.argb(0x74, 0x2A, 0x2A, 0x30)
    val GlassSoft = Color.argb(0x8A, 0x2A, 0x2A, 0x30)
    val Fill = Color.argb(0x2E, 0x78, 0x78, 0x80)
    val Hairline = Color.argb(0x1A, 0xFF, 0xFF, 0xFF)
    val Green = Color.rgb(0x30, 0xD1, 0x58)
    val Orange = Color.rgb(0xFF, 0x9F, 0x0A)
    val Red = Color.rgb(0xFF, 0x45, 0x3A)
    val Focus = Color.rgb(0xF5, 0xF5, 0xF7)
    val Scrim = Color.argb(24, 2, 8, 20)

    fun typeface(context: Context, bold: Boolean = false): Typeface {
        if (android.os.Build.VERSION.SDK_INT < 26) {
            return Typeface.create(Typeface.SANS_SERIF, if (bold) Typeface.BOLD else Typeface.NORMAL)
        }
        val font = ResourcesCompat.getFont(context, R.font.inter) ?: Typeface.SANS_SERIF
        return if (android.os.Build.VERSION.SDK_INT >= 28) {
            Typeface.create(font, if (bold) 600 else 500, false)
        } else {
            Typeface.create(font, if (bold) Typeface.BOLD else Typeface.NORMAL)
        }
    }

    fun panel(context: Context, cornerDp: Float, soft: Boolean = false): GradientDrawable =
        GradientDrawable(
            GradientDrawable.Orientation.TL_BR,
            intArrayOf(Color.argb(0x70, 0x36, 0x36, 0x3C), Color.argb(0x9A, 0x12, 0x12, 0x18)),
        ).apply {
            cornerRadius = cornerDp * context.resources.displayMetrics.density
            setStroke(
                (1 * context.resources.displayMetrics.density).toInt().coerceAtLeast(1),
                Hairline,
            )
        }
}
