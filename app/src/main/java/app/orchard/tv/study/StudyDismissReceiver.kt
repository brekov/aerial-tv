package app.orchard.tv.study

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Runs in :study so the main process can close the Activity. */
class StudyDismissReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        StudyActivity.finishCurrent()
    }
}
