package app.orchard.tv.study

import android.content.Context
import android.view.View
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.unit.dp
import app.orchard.tv.ui.components.liquidGlass

/** Full-page Aerial LiquidGlass backdrop for the native repeat-learning Activity. */
internal fun studyGlassView(context: Context): View = ComposeView(context).apply {
    setContent {
        Box(Modifier.fillMaxSize().liquidGlass(0.dp))
    }
}
