package app.orchard.tv.study

import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import androidx.core.content.getSystemService
import app.orchard.tv.dream.AerialDream
import app.orchard.tv.guard.HomeGuardService
import app.orchard.tv.settings.Restricted
import app.orchard.tv.system.DiagLog

/**
 * Counts watching outside Aerial's own Home and starts the quiz when [StudySettings.intervalMs]
 * has passed. Modeled on KidsWatch but independent of Kids/Elders mode.
 *
 * Only apps in front count: Aerial's Home, its screensaver, settings and the quiz itself do not.
 * Ten minutes of a held-up process is not credited as watching either (see [TICK_MS]).
 */
object StudyWatch {
    private const val TAG = "AerialStudy"
    private const val TICK_MS = 5_000L
    private val handler = Handler(Looper.getMainLooper())
    private var app: Context? = null
    private var running = false
    private var lastTickAt = 0L
    private var lastWatchingAt = 0L

    private val loop = Runnable { tickAndPlan() }

    fun start(context: Context) {
        StudySettings.init(context)
        app = context.applicationContext
        poke()
    }

    fun poke() {
        val ctx = app ?: return
        if (!StudySettings.enabled) {
            running = false
            lastTickAt = 0L
            handler.removeCallbacks(loop)
            return
        }
        handler.removeCallbacks(loop)
        handler.post(loop)
    }

    private fun tickAndPlan() {
        val ctx = app ?: return
        if (!StudySettings.enabled) {
            running = false
            lastTickAt = 0L
            return
        }
        running = true
        val now = SystemClock.elapsedRealtime()
        val since = if (lastTickAt == 0L) 0L else (now - lastTickAt).coerceAtLeast(0L).coerceAtMost(2 * TICK_MS)
        lastTickAt = now
        if (watching(ctx)) {
            if (lastWatchingAt != 0L && now - lastWatchingAt > 2 * 60_000L) StudySettings.resetWatch()
            lastWatchingAt = now
            StudySettings.addWatch(since)
        }
        if (StudySettings.watchMs >= StudySettings.intervalMs && !StudyOverlay.active) {
            DiagLog.i("study: ${StudySettings.intervalMinutes} min watched; opening the quiz")
            if (!StudyOverlay.show(ctx)) Log.w(TAG, "Home Guard is not running; cannot show the study overlay")
        }
        handler.postDelayed(loop, TICK_MS)
    }

    private fun watching(ctx: Context): Boolean {
        if (!StudySettings.enabled) return false
        if (!ctx.getSystemService<PowerManager>()?.isInteractive.orFalse()) return false
        if (Restricted.active) return false
        if (AerialDream.showing) return false
        if (StudyOverlay.active) return false
        val front = frontByUsage(ctx) ?: return false
        if (front == ctx.packageName) return false
        if (front.startsWith("com.xiaomi.mitv.settings") || front.startsWith("com.android.tv.settings")) return false
        return HomeGuardService.usageStatsAllowed(ctx)
    }

    private fun Boolean?.orFalse() = this == true

    private fun frontByUsage(ctx: Context): String? = runCatching {
        val manager = ctx.getSystemService<UsageStatsManager>() ?: return null
        val now = System.currentTimeMillis()
        val events = manager.queryEvents(now - 60_000L, now)
        val event = UsageEvents.Event()
        var last: String? = null
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            if (event.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND) last = event.packageName
        }
        last
    }.getOrNull()
}
