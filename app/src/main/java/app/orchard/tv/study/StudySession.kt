package app.orchard.tv.study

/** Local state in the :study process for the repeat-learning Activity. */
object StudySession {
    @Volatile var active: Boolean = false
        internal set
}
