package app.orchard.tv.wallpaper

import android.content.Context
import android.util.Log
import androidx.core.content.edit
import app.orchard.tv.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.URI
import java.net.URL

/**
 * The daily wallpaper source. Bing is the default; a custom source must be a LAN address and is
 * validated against the token-authenticated /health of the NAS server. Discovery tries the NAS
 * mDNS name, the last known IP, then a scan of the TV's own /24 (NsdManager is unreliable on the
 * Xiaomi firmware, so it is not used).
 */
object DailySource {
    private const val TAG = "AerialDailySource"
    private const val PREFS = "daily_source"
    private const val KEY_CUSTOM = "custom_base"
    private const val KEY_LAST_IP = "last_lan_ip"
    const val BING_BASE = "https://cn.bing.com"
    const val BING_JSON = "$BING_BASE/HPImageArchive.aspx?format=js&idx=0&n=8&mkt=zh-CN"
    const val LAN_HOST = "saboop.local"
    const val PORT = 8899
    private const val TOKEN_HEADER = "X-Aerial-Token"

    /** The stored custom base, if it is still a valid LAN address. */
    fun customBase(context: Context): String? {
        val stored = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_CUSTOM, null)
        return stored?.let(::normalize)
    }

    fun label(context: Context): String = customBase(context) ?: BING_BASE

    /** Saves a normalized base after the LAN and health checks in [setIfHealthy]. */
    fun save(context: Context, base: String): Boolean {
        val normalized = normalize(base) ?: return false
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit { putString(KEY_CUSTOM, normalized) }
        return true
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit { remove(KEY_CUSTOM) }
    }

    /** Strict: http only, port 8899 only, private IPv4 or .local, no path/query/userinfo. */
    fun normalize(input: String): String? {
        val text = input.trim().trimEnd('/')
        if (!text.startsWith("http://", ignoreCase = true)) return null
        val uri = runCatching { URI(text) }.getOrNull() ?: return null
        if (!uri.scheme.equals("http", ignoreCase = true)) return null
        if (!uri.userInfo.isNullOrEmpty() || !uri.query.isNullOrEmpty() || !uri.fragment.isNullOrEmpty()) return null
        if (!uri.path.isNullOrEmpty()) return null
        val host = uri.host?.lowercase() ?: return null
        val port = if (uri.port == -1) PORT else uri.port
        if (port != PORT) return null
        if (!isLanHost(host)) return null
        return "http://$host:$PORT"
    }

    private fun isLanHost(host: String): Boolean {
        if (host.endsWith(".local") && host.length > ".local".length) return true
        val ip = parseIpv4(host) ?: return false
        return isPrivate(ip)
    }

    private fun isPrivate(ip: IntArray): Boolean =
        ip[0] == 10 ||
            (ip[0] == 172 && ip[1] in 16..31) ||
            (ip[0] == 192 && ip[1] == 168)

    private fun parseIpv4(text: String): IntArray? {
        val parts = text.split('.')
        if (parts.size != 4) return null
        val out = IntArray(4)
        for (i in 0..3) {
            val n = parts[i].toIntOrNull() ?: return null
            if (n !in 0..255) return null
            out[i] = n
        }
        return out
    }

    /** A .local name must resolve to a private IPv4; an IPv4 literal is checked syntactically. */
    private fun resolvesToLan(host: String): Boolean {
        if (!host.endsWith(".local")) return true
        return runCatching {
            InetAddress.getAllByName(host).any { it is Inet4Address && isPrivate(parseIpv4(it.hostAddress) ?: return@any false) }
        }.getOrDefault(false)
    }

    suspend fun health(base: String, timeoutMs: Int = 1500): Boolean = withContext(Dispatchers.IO) {
        val normalized = normalize(base) ?: return@withContext false
        val host = URI(normalized).host ?: return@withContext false
        if (!resolvesToLan(host)) return@withContext false
        runCatching {
            val c = URL("$normalized/health").openConnection() as HttpURLConnection
            c.connectTimeout = timeoutMs
            c.readTimeout = timeoutMs
            c.setRequestProperty(TOKEN_HEADER, BuildConfig.DAILY_TOKEN)
            val code = c.responseCode
            val body = if (code == 200) c.inputStream.use { it.readBytes().decodeToString() } else ""
            c.disconnect()
            code == 200 && body.contains("aerial-daily")
        }.getOrElse { false }
    }

    /** Validates and saves a manually entered base. */
    suspend fun setIfHealthy(context: Context, input: String): Boolean {
        val normalized = normalize(input) ?: return false
        if (!health(normalized)) return false
        return save(context, normalized)
    }

    /**
     * Finds a LAN daily server: the NAS mDNS name first, then the last working IP, then a scan of
     * the TV's own /24. Only returns a source whose token-authenticated health check passed.
     */
    suspend fun probe(context: Context): String? = withContext(Dispatchers.IO) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val hostBase = "http://$LAN_HOST:$PORT"
        if (health(hostBase)) return@withContext hostBase

        val last = prefs.getString(KEY_LAST_IP, null)
        if (!last.isNullOrBlank()) {
            val lastBase = "http://$last:$PORT"
            if (health(lastBase)) return@withContext lastBase
        }

        val local = localIpv4() ?: return@withContext null
        if (!isPrivate(parseIpv4(local) ?: return@withContext null)) return@withContext null
        val prefix = local.substringBeforeLast('.') + "."
        val hits = scan(prefix, PORT)
        val found = coroutineScope {
            hits.map { ip ->
                async { val b = "http://$ip:$PORT"; if (health(b, 1200)) b else null }
            }.awaitAll().firstOrNull { it != null }
        }
        if (found != null) {
            val ip = URI(found).host
            prefs.edit { putString(KEY_LAST_IP, ip) }
            return@withContext found
        }
        null
    }

    private suspend fun scan(prefix: String, port: Int): List<String> = coroutineScope {
        val semaphore = Semaphore(32)
        (1..254).map { i ->
            async(Dispatchers.IO) {
                semaphore.withPermit {
                    val ip = prefix + i
                    runCatching {
                        java.net.Socket().use { s ->
                            s.connect(java.net.InetSocketAddress(ip, port), 300)
                            ip
                        }
                    }.getOrNull()
                }
            }
        }.awaitAll().filterNotNull()
    }

    private fun localIpv4(): String? {
        runCatching {
            val interfaces = NetworkInterface.getNetworkInterfaces()
            while (interfaces.hasMoreElements()) {
                val ni = interfaces.nextElement()
                if (!ni.isUp || ni.isLoopback) continue
                val addresses = ni.inetAddresses
                while (addresses.hasMoreElements()) {
                    val a = addresses.nextElement()
                    if (a is Inet4Address && !a.isLoopbackAddress && a.isSiteLocalAddress) return a.hostAddress
                }
            }
        }.onFailure { Log.w(TAG, "local ip lookup failed", it) }
        return null
    }
}
