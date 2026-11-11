package app.orchard.tv.ui.wallpaper

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import app.orchard.tv.R
import app.orchard.tv.ui.components.consumeTaps
import app.orchard.tv.ui.components.liquidGlass
import app.orchard.tv.ui.theme.Glyph
import app.orchard.tv.ui.theme.Palette
import app.orchard.tv.ui.theme.Type

/** Custom watch interval, 1–120 minutes. */
@Composable
internal fun StudyDurationDialog(initial: Int, onSave: (Int) -> Unit, onClose: () -> Unit) {
    BackHandler(onBack = onClose)
    var value by remember { mutableStateOf(initial.coerceIn(1, 120).toString()) }
    val focus = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current
    LaunchedEffect(Unit) { focus.requestFocus(); keyboard?.show() }
    Column(Modifier.width(620.dp).liquidGlass(28.dp).padding(24.dp).consumeTaps(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        BasicText(stringResource(R.string.study_duration_custom_title), style = Type.Headline)
        BasicText(stringResource(R.string.study_duration_custom_hint), style = Type.Caption.copy(color = Palette.SecondaryLabel))
        BasicTextField(
            value = value,
            onValueChange = { value = it.filter(Char::isDigit).take(3) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            textStyle = Type.Body.copy(color = Palette.Label),
            cursorBrush = SolidColor(Palette.Focus),
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Palette.Fill)
                .padding(10.dp).focusRequester(focus),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            ActionChip(stringResource(R.string.study_duration_save), Glyph.Check) {
                val minutes = value.toIntOrNull()?.coerceIn(1, 120) ?: initial
                onSave(minutes)
            }
            ActionChip(stringResource(R.string.study_mimo_cancel), Glyph.ChevronLeft, onClose)
        }
    }
}
