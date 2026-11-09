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
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import app.orchard.tv.R
import app.orchard.tv.study.StudySettings
import app.orchard.tv.ui.components.consumeTaps
import app.orchard.tv.ui.components.liquidGlass
import app.orchard.tv.ui.theme.Glyph
import app.orchard.tv.ui.theme.Palette
import app.orchard.tv.ui.theme.Type

/** Set the optional per-TV MiMo key. Kept on the device; never logged or sent to the NAS. */
@Composable
internal fun StudyMimoDialog(onClose: () -> Unit) {
    BackHandler(onBack = onClose)
    val context = LocalContext.current
    var key by remember { mutableStateOf(StudySettings.mimoApiKey) }
    var status by remember { mutableStateOf<String?>(null) }
    val focus = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current
    LaunchedEffect(Unit) {
        focus.requestFocus()
        keyboard?.show()
    }
    Column(
        Modifier.width(720.dp).liquidGlass(28.dp).padding(24.dp).consumeTaps(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        BasicText(stringResource(R.string.study_mimo_title), style = Type.Headline)
        BasicText(
            stringResource(R.string.study_mimo_hint),
            style = Type.Caption.copy(color = Palette.SecondaryLabel),
        )
        BasicText(stringResource(R.string.study_mimo_field), style = Type.Caption.copy(color = Palette.SecondaryLabel))
        BasicTextField(
            value = key,
            onValueChange = { key = it.trim() },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            textStyle = Type.Body.copy(color = Palette.Label),
            cursorBrush = SolidColor(Palette.Focus),
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(10.dp))
                .background(Palette.Fill)
                .padding(10.dp)
                .focusRequester(focus)
                .onFocusChanged { if (it.isFocused) keyboard?.show() },
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            ActionChip(stringResource(R.string.study_mimo_saved), Glyph.Check) {
                StudySettings.mimoApiKey = key
                status = context.getString(if (key.isBlank()) R.string.study_mimo_unset else R.string.study_mimo_saved)
            }
            ActionChip(stringResource(R.string.study_mimo_clear), Glyph.Trash) {
                key = ""
                StudySettings.mimoApiKey = ""
                status = context.getString(R.string.study_mimo_unset)
            }
            ActionChip(stringResource(R.string.study_mimo_cancel), Glyph.ChevronLeft, onClose)
        }
        status?.let { BasicText(it, style = Type.Caption.copy(color = Palette.SecondaryLabel)) }
    }
}
