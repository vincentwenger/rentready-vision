package com.rentreadyvision.tv

import android.os.Looper
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.URL
import java.util.UUID
import javax.net.ssl.HttpsURLConnection

class TvPairingException(
    val friendlyMessage: String
) : IOException()

/**
 * Exchanges a one-time pairing code over verified production HTTPS.
 *
 * No operator token is needed or stored on the TV.
 * POST is never automatically retried.
 */
object TvPairingClient {
    private const val ENDPOINT =
        "https://rentreadyvision.com/api/tv/pairings/redeem"

    private const val MAX_RESPONSE_BYTES = 4096

    private val codePattern = Regex(
        "[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{5}-" +
            "[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{5}"
    )

    private val tokenPattern =
        Regex("rrtv1_[A-Za-z0-9_-]{43}")

    fun redeem(code: String): TvDeviceSession {
        check(Looper.myLooper() != Looper.getMainLooper()) {
            "Pairing network operation must run off the UI thread"
        }

        require(codePattern.matches(code)) {
            "Invalid pairing-code format"
        }

        val requestBody = JSONObject()
            .put("code", code)
            .toString()
            .toByteArray(Charsets.UTF_8)

        val connection = URL(ENDPOINT).openConnection()
            as HttpsURLConnection

        connection.requestMethod = "POST"
        connection.connectTimeout = 8000
        connection.readTimeout = 12000
        connection.instanceFollowRedirects = false
        connection.useCaches = false
        connection.doOutput = true

        connection.setRequestProperty(
            "Content-Type", "application/json"
        )
        connection.setRequestProperty(
            "Accept", "application/json"
        )
        connection.setRequestProperty(
            "Accept-Encoding", "identity"
        )

        try {
            connection.outputStream.use {
                it.write(requestBody)
            }

            when (connection.responseCode) {
                400 -> throw TvPairingException(
                    "The code is invalid or has expired. " +
                        "Request a new code."
                )

                429 -> throw TvPairingException(
                    "Too many attempts. Wait five minutes " +
                        "before trying again."
                )

                503 -> throw TvPairingException(
                    "TV pairing is temporarily unavailable."
                )

                200 -> Unit

                else -> throw TvPairingException(
                    "Could not complete TV pairing."
                )
            }

            require(
                connection.contentType
                    .substringBefore(";")
                    .trim()
                    .equals("application/json", ignoreCase = true)
            ) {
                "Unexpected pairing response type"
            }

            val declared = connection.contentLengthLong

            require(
                declared == -1L ||
                    declared in 1L..MAX_RESPONSE_BYTES.toLong()
            ) {
                "Unexpected pairing response size"
            }

            val output = ByteArrayOutputStream()

            connection.inputStream.use { input ->
                val buffer = ByteArray(1024)

                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    if (count == 0) continue

                    require(
                        output.size() + count <= MAX_RESPONSE_BYTES
                    ) {
                        "Pairing response too large"
                    }

                    output.write(buffer, 0, count)
                }
            }

            val bytes = output.toByteArray()

            if (declared >= 0) {
                require(bytes.size.toLong() == declared) {
                    "Incomplete pairing response"
                }
            }

            val payload = JSONObject(
                String(bytes, Charsets.UTF_8)
            )

            val token = payload.getString("token")
            val inspection = payload.getString("inspection_id")
            val deviceId = payload.getString("device_id")
            val expiresAt = payload.getLong("expires_at")

            require(tokenPattern.matches(token)) {
                "Invalid TV-device token"
            }

            require(
                UUID.fromString(inspection).toString() == inspection &&
                    UUID.fromString(deviceId).toString() == deviceId
            ) {
                "Invalid TV pairing identity"
            }

            val now = System.currentTimeMillis() / 1000L

            require(
                expiresAt > now &&
                    expiresAt - now <= 7L * 24L * 60L * 60L
            ) {
                "Invalid TV pairing expiration"
            }

            require(
                connection.getHeaderField("Cache-Control")
                    ?.contains("no-store", ignoreCase = true) == true
            ) {
                "Missing credential-response cache protection"
            }

            return TvDeviceSession(
                token = token,
                inspectionId = inspection,
                expiresAtEpochSeconds = expiresAt
            )
        } finally {
            connection.disconnect()
        }
    }
}
