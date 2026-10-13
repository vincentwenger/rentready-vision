package com.rentreadyvision.tv

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * One inspection-scoped TV session issued by the RentReady backend.
 * Never write the token to logs or bundle it inside the APK.
 */
data class TvDeviceSession(
    val token: String,
    val inspectionId: String,
    val expiresAtEpochSeconds: Long
)

/**
 * Encrypts the session using a non-exportable AndroidKeyStore key.
 *
 * Only encrypted ciphertext is persisted in private preferences.
 * This does not issue credentials or make network requests.
 */
object TvDeviceSessionStore {
    private const val KEY_ALIAS =
        "rentready_tv_device_session_aes_v1"

    private const val PREF_NAME =
        "rentready_tv_credentials_v1"

    private const val PREF_KEY = "encrypted_session"

    private const val AAD = "rentready-tv-session-v1"

    private const val IV_BYTES = 12
    private const val TAG_BITS = 128
    private const val MAX_ENCODED_BYTES = 4096
    private const val MAX_LIFETIME_SECONDS = 7L * 24L * 60L * 60L

    private val tokenPattern =
        Regex("rrtv1_[A-Za-z0-9_-]{43}")

    private fun preferences(context: Context) =
        context.applicationContext.getSharedPreferences(
            PREF_NAME,
            Context.MODE_PRIVATE
        )

    private fun encryptionKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore")
        store.load(null)

        val existing = store.getKey(KEY_ALIAS, null)
        if (existing is SecretKey) return existing

        val generator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            "AndroidKeyStore"
        )

        val specification = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or
                KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(
                KeyProperties.ENCRYPTION_PADDING_NONE
            )
            .setKeySize(256)
            .setRandomizedEncryptionRequired(true)
            .build()

        generator.init(specification)
        return generator.generateKey()
    }

    private fun valid(session: TvDeviceSession): Boolean {
        val canonicalInspection = try {
            UUID.fromString(session.inspectionId).toString() ==
                session.inspectionId
        } catch (_: IllegalArgumentException) {
            false
        }

        val now = System.currentTimeMillis() / 1000L
        val remaining = session.expiresAtEpochSeconds - now

        return (
            tokenPattern.matches(session.token) &&
                canonicalInspection &&
                remaining > 0L &&
                remaining <= MAX_LIFETIME_SECONDS
        )
    }

    fun save(context: Context, session: TvDeviceSession) {
        require(valid(session)) {
            "Invalid or expired TV-device session"
        }

        val payload = JSONObject()
            .put("token", session.token)
            .put("inspection_id", session.inspectionId)
            .put("expires_at", session.expiresAtEpochSeconds)
            .toString()
            .toByteArray(Charsets.UTF_8)

        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, encryptionKey())
        cipher.updateAAD(AAD.toByteArray(Charsets.UTF_8))

        val ciphertext = cipher.doFinal(payload)
        val iv = cipher.iv

        check(iv.size == IV_BYTES) {
            "Unexpected encryption nonce length"
        }

        val encoded = Base64.encodeToString(
            iv + ciphertext,
            Base64.NO_WRAP
        )

        check(
            preferences(context)
                .edit()
                .putString(PREF_KEY, encoded)
                .commit()
        ) {
            "TV-device session could not be saved"
        }
    }

    fun load(context: Context): TvDeviceSession? {
        return try {
            val encoded = preferences(context)
                .getString(PREF_KEY, null)
                ?: return null

            val bytes = Base64.decode(
                encoded,
                Base64.NO_WRAP
            )

            require(
                bytes.size in (IV_BYTES + 17)..MAX_ENCODED_BYTES
            ) {
                "Invalid encrypted session size"
            }

            val iv = bytes.copyOfRange(0, IV_BYTES)
            val ciphertext = bytes.copyOfRange(
                IV_BYTES,
                bytes.size
            )

            val cipher = Cipher.getInstance(
                "AES/GCM/NoPadding"
            )

            cipher.init(
                Cipher.DECRYPT_MODE,
                encryptionKey(),
                GCMParameterSpec(TAG_BITS, iv)
            )

            cipher.updateAAD(AAD.toByteArray(Charsets.UTF_8))

            val payload = JSONObject(
                String(
                    cipher.doFinal(ciphertext),
                    Charsets.UTF_8
                )
            )

            val session = TvDeviceSession(
                token = payload.getString("token"),
                inspectionId = payload.getString("inspection_id"),
                expiresAtEpochSeconds =
                    payload.getLong("expires_at")
            )

            if (!valid(session)) {
                clear(context)
                null
            } else {
                session
            }
        } catch (_: Exception) {
            // Includes invalidated Keystore keys, corrupted
            // ciphertext, tampering, and malformed sessions.
            clear(context)
            null
        }
    }

    fun clear(context: Context) {
        check(
            preferences(context)
                .edit()
                .remove(PREF_KEY)
                .commit()
        ) {
            "TV-device session could not be cleared"
        }
    }
}
