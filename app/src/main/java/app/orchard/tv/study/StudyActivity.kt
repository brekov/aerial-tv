package app.orchard.tv.study

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.view.WindowManager.LayoutParams
import android.os.Bundle
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import app.orchard.tv.guard.HomeGuardService
import app.orchard.tv.system.DiagLog

/**
 * Full-screen repeat-learning Activity. It owns its task, so the video app below it is paused by
 * the normal Activity lifecycle and resumes when this task is removed.
 */
class StudyActivity : Activity() {
    companion object {
        private const val TAG = "AerialStudy"
        const val EXTRA_ACTIVE = "app.orchard.tv.study.ACTIVE"
        private var current: StudyActivity? = null

        /**
         * Start from the accessibility service when possible: that context is not subject to
         * normal background-Activity launch restrictions. Fall back to the caller's context.
         */
        fun launch(context: Context): Boolean {
            StudySettings.init(context)
            if (!StudySettings.enabled) return false
            val service = HomeGuardService.studyService()
            val starter = service ?: context
            val intent = Intent(service ?: context, StudyActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_CLEAR_TOP or
                    Intent.FLAG_ACTIVITY_NO_ANIMATION,
            )
            return runCatching {
                starter.startActivity(intent)
                true
            }.getOrElse {
                DiagLog.i("study: Activity launch failed: ${it.javaClass.simpleName}")
                false
            }
        }

        /** Main-process callers cannot touch [current] in :study; ask that process to close. */
        fun requestDismiss(context: Context) {
            context.sendBroadcast(Intent(context, StudyDismissReceiver::class.java))
        }

        internal fun finishCurrent() {
            current?.let { activity ->
                activity.runOnUiThread {
                    StudySession.active = false
                    activity.finishAndRemoveTask()
                }
            }
        }
    }

    private var screen: StudyScreen? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        StudySettings.init(this)
        if (!StudySettings.enabled) {
            finish()
            return
        }
        current = this
        StudySession.active = true
        sendState(true)
        window.addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_FULLSCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
        )
        window.setBackgroundDrawable(android.graphics.drawable.ColorDrawable(Color.TRANSPARENT))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val attrs = window.attributes
            attrs.flags = attrs.flags or LayoutParams.FLAG_BLUR_BEHIND
            attrs.blurBehindRadius = (28 * resources.displayMetrics.density).toInt()
            window.attributes = attrs
        }
        window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
        screen = StudyScreen(this).also { it.start() }
        DiagLog.i("study: Activity shown")
    }

    override fun onStop() {
        super.onStop()
        // If the Activity is covered or the user leaves the task, never leave a background timer
        // retrying session creation.
        if (!isFinishing) {
            StudySession.active = false
            screen?.shutdown()
            finishAndRemoveTask()
        }
    }

    override fun onDestroy() {
        StudySession.active = false
        sendState(false)
        if (current === this) current = null
        screen?.shutdown()
        screen = null
        super.onDestroy()
        DiagLog.i("study: Activity closed")
    }

    private fun sendState(active: Boolean) {
        sendBroadcast(
            Intent(this, StudyStateReceiver::class.java)
                .setPackage(packageName)
                .putExtra(EXTRA_ACTIVE, active)
        )
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            window.decorView.systemUiVisibility =
                View.SYSTEM_UI_FLAG_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
        }
    }

    @Deprecated("Blocked while repeat learning is active")
    override fun onBackPressed() {
        // Back, Home and voice keys are owned by the guard and the Activity.
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode == KeyEvent.KEYCODE_POWER) return super.dispatchKeyEvent(event)
        return true
    }
}
