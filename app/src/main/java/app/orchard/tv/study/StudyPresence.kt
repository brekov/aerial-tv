package app.orchard.tv.study

/** Main-process view of whether the isolated study process is showing its Activity. */
object StudyPresence {
    @Volatile var active: Boolean = false
        internal set
}
