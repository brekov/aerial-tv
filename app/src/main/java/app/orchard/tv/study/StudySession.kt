package app.orchard.tv.study

/** Cross-component state for the repeat-learning Activity, same process as HomeGuardService. */
object StudySession {
    @Volatile var active: Boolean = false
        internal set
}
