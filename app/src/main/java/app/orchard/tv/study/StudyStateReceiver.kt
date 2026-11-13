package app.orchard.tv.study

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Main process receives study-process lifecycle changes for HomeGuard/StudyWatch. */
class StudyStateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        StudyPresence.active = intent.getBooleanExtra(StudyActivity.EXTRA_ACTIVE, false)
        StudyWatch.poke()
    }
}
