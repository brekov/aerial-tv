package app.orchard.tv.study

import android.content.Context
import android.view.View
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.unit.dp
import app.orchard.tv.ui.components.liquidGlass

/** The Aerial LiquidGlass material, hosted over the native Activity layout. */
internal fun studyGlassView(context: Context): View = ComposeView(context).apply {
    setContent {
        Box(Modifier.fillMaxSize()) {
            Box(
                Modifier
                    .padding(start = 14.dp, top = 16.dp, bottom = 12.dp)
                    .fillMaxHeight()
                    .fillMaxWidth(0.25f)
                    .liquidGlass(30.dp),
            )
        }
    }
}
