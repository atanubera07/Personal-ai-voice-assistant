package `in`.personal.agent

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.security.MessageDigest
import java.util.UUID

class Backend(private val settings: ConnectionSettings) {
    suspend fun request(path: String, method: String = "GET", body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        check(settings.url.isNotBlank()) { "Connect your backend in Settings first." }
        val uri = URI(settings.url)
        check(uri.scheme == "https" || (BuildConfig.DEBUG && uri.scheme == "http")) { "Use an HTTPS backend address." }
        check(uri.userInfo == null && uri.query == null && uri.fragment == null && uri.path in listOf("", "/")) { "Use the backend origin without a path, username or query." }
        val target = URI(settings.url.trimEnd('/') + path)
        val payload = body?.toString()?.toByteArray(Charsets.UTF_8) ?: byteArrayOf()
        val token = settings.token
        fun hash(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        val connection = target.toURL().openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 10000
            connection.readTimeout = 15000
            connection.instanceFollowRedirects = false
            if (token.isNotBlank() && !path.startsWith("/v1/auth/challenge") && !path.startsWith("/v1/auth/device-session") && !path.startsWith("/v1/auth/enroll")) {
                connection.setRequestProperty("Authorization", "Bearer $token")
                val timestamp = (System.currentTimeMillis() / 1000).toString()
                val nonce = UUID.randomUUID().toString()
                val requestTarget = target.rawPath + (target.rawQuery?.let { "?$it" } ?: "")
                val message = listOf("personal-agent-request-v1", method, requestTarget, hash(payload),
                    hash(token.toByteArray(Charsets.UTF_8)), timestamp, nonce).joinToString("\n")
                connection.setRequestProperty("X-Device-Timestamp", timestamp)
                connection.setRequestProperty("X-Device-Nonce", nonce)
                connection.setRequestProperty("X-Device-Signature", DeviceIdentity.sign(message))
            }
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(payload) }
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val result = stream?.bufferedReader()?.use { JSONObject(it.readText()) } ?: JSONObject()
            if (code == 401) { settings.token = ""; error("Session expired. Sign in again in Settings.") }
            check(code in 200..299) { result.optString("detail", "Connection failed ($code)") }
            result
        } finally { connection.disconnect() }
    }
}
