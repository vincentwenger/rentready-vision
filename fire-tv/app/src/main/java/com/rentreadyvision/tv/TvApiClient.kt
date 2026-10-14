package com.rentreadyvision.tv

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Looper
import android.util.Log
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.URI
import java.net.URL
import java.util.Locale
import java.util.UUID
import javax.net.ssl.HttpsURLConnection

/**
 * Development-only client for the loopback Fire TV emulator bridge.
 *
 * No operator API token or AWS credentials are used.
 * Must run on a background thread.
 * A public or production Fire TV app requires separate authentication.
 */
object TvApiClient {

    private const val BASE_URL = "https://rentreadyvision.com"
    private const val MAX_RESPONSE_BYTES = 1_000_000
    private const val MAX_IMAGE_BYTES = 8_000_000
    private const val MAX_IMAGE_WIDTH = 1920
    private const val MAX_IMAGE_HEIGHT = 1080

    private fun getJson(context: Context, path: String): JSONObject {
        var lastTransportError: java.io.IOException? = null

        for (attempt in 1..3) {
            try {
                return getJsonOnce(context, path)
            } catch (failure: java.io.IOException) {
                lastTransportError = failure

                Log.w(
                    "RentReadyTV",
                    "HTTP transport attempt $attempt/3 failed: " +
                        failure.javaClass.simpleName
                )

                if (attempt < 3) {
                    Thread.sleep(250L * attempt)
                }
            }
        }

        throw (lastTransportError ?: java.io.IOException(
            "TV HTTP request failed"
        ))
    }

    private fun getJsonOnce(context: Context, path: String): JSONObject {
        require(path.startsWith("/api/tv/")) {
            "Unsupported TV API path"
        }

        val session = TvDeviceSessionStore.load(context)
            ?: throw SecurityException("TV pairing required")

        val connection = (
            URL(BASE_URL + path).openConnection()
                as HttpsURLConnection
        )

        connection.requestMethod = "GET"
        connection.connectTimeout = 5_000
        connection.readTimeout = 10_000
        connection.instanceFollowRedirects = false
        connection.useCaches = false
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty(
            "Authorization", "Bearer " + session.token
        )
        connection.setRequestProperty("Accept-Encoding", "identity")

        try {
            val status = connection.responseCode

            if (status == 401 || status == 403) {
                TvDeviceSessionStore.clear(context)
                throw SecurityException(
                    "TV device authorization expired or revoked"
                )
            }

            if (status != 200) {
                throw java.io.IOException(
                    "TV API request failed (HTTP $status)"
                )
            }

            val declaredLength = connection.contentLengthLong

            require(
                declaredLength == -1L ||
                    declaredLength in 1L..MAX_RESPONSE_BYTES.toLong()
            ) {
                "Invalid TV response length"
            }

            val output = ByteArrayOutputStream()

            connection.inputStream.use { input ->
                val buffer = ByteArray(8192)

                while (true) {
                    val count = input.read(buffer)

                    if (count < 0) break
                    if (count == 0) continue

                    require(
                        output.size() + count <= MAX_RESPONSE_BYTES
                    ) {
                        "TV response too large"
                    }

                    output.write(buffer, 0, count)
                }
            }

            val bytes = output.toByteArray()

            require(bytes.isNotEmpty()) {
                "Empty TV response"
            }

            if (declaredLength >= 0L) {
                require(bytes.size.toLong() == declaredLength) {
                    "Incomplete TV HTTP response"
                }
            }

            return JSONObject(String(bytes, Charsets.UTF_8))
        } finally {
            connection.disconnect()
        }
    }


    /**
     * Download preserved evidence for one finding.
     *
     * Requests a fresh authenticated image grant over production HTTPS.
     * Never logs signed URLs or downloads on the Android main thread.
     */
    fun loadEvidenceImage(
        context: Context,
        inspectionId: String,
        findingId: String
    ): Bitmap {
        check(Looper.myLooper() != Looper.getMainLooper()) {
            "Evidence must load off the UI thread"
        }

        require(UUID.fromString(inspectionId).toString() == inspectionId) {
            "Invalid inspection identifier"
        }

        require(Regex("[0-9a-f]{32}").matches(findingId)) {
            "Invalid finding identifier"
        }

        val path = (
            "/api/tv/inspections/$inspectionId/" +
                "findings/$findingId/image-url"
        )

        val grant = getJson(context, path)

        require(grant.getInt("expires_in_seconds") in 1..120) {
            "Unexpected image grant duration"
        }

        val signedUrl = URI(grant.getString("url"))
        val host = signedUrl.host?.lowercase(Locale.ROOT) ?: ""

        val approvedHost = (
            host == "s3.amazonaws.com" ||
                host.matches(
                    Regex("""s3[.-][a-z0-9-]+\.amazonaws\.com""")
                ) ||
                host.matches(
                    Regex("""[a-z0-9][a-z0-9.-]*\.s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com""")
                )
        )

        require(
            signedUrl.scheme == "https" &&
                approvedHost &&
                signedUrl.rawUserInfo == null &&
                signedUrl.port in listOf(-1, 443) &&
                signedUrl.rawFragment == null &&
                signedUrl.rawQuery?.contains(
                    "X-Amz-Signature="
                ) == true
        ) {
            "Untrusted evidence URL"
        }

        val connection = (
            signedUrl.toURL().openConnection()
                as HttpsURLConnection
        )

        connection.requestMethod = "GET"
        connection.connectTimeout = 5_000
        connection.readTimeout = 15_000
        connection.instanceFollowRedirects = false
        connection.useCaches = false
        connection.setRequestProperty(
            "Accept", "image/jpeg,image/png,image/webp"
        )
        connection.setRequestProperty("Accept-Encoding", "identity")

        try {
            check(connection.responseCode == 200) {
                "Preserved image is unavailable"
            }

            val mediaType = connection.contentType
                .substringBefore(";")
                .trim()
                .lowercase(Locale.ROOT)

            require(
                mediaType in setOf(
                    "image/jpeg", "image/png", "image/webp"
                )
            ) {
                "Unexpected evidence media type"
            }

            val declaredSize = connection.contentLengthLong

            require(
                declaredSize == -1L ||
                    declaredSize in 1L..MAX_IMAGE_BYTES.toLong()
            ) {
                "Evidence image exceeds download limit"
            }

            val output = ByteArrayOutputStream()
            val buffer = ByteArray(8192)

            connection.inputStream.use { input ->
                while (true) {
                    val count = input.read(buffer)

                    if (count < 0) break
                    if (count == 0) continue

                    require(
                        output.size() + count <= MAX_IMAGE_BYTES
                    ) {
                        "Evidence image exceeds download limit"
                    }

                    output.write(buffer, 0, count)
                }
            }

            val bytes = output.toByteArray()

            require(bytes.isNotEmpty()) {
                "Empty evidence image"
            }

            if (declaredSize >= 0L) {
                require(bytes.size.toLong() == declaredSize) {
                    "Incomplete evidence image"
                }
            }

            val bounds = BitmapFactory.Options().apply {
                inJustDecodeBounds = true
            }

            BitmapFactory.decodeByteArray(
                bytes, 0, bytes.size, bounds
            )

            require(
                bounds.outWidth in 1..16_000 &&
                    bounds.outHeight in 1..16_000
            ) {
                "Invalid evidence image dimensions"
            }

            var sample = 1

            while (
                bounds.outWidth / sample > MAX_IMAGE_WIDTH ||
                    bounds.outHeight / sample > MAX_IMAGE_HEIGHT
            ) {
                sample *= 2
            }

            val options = BitmapFactory.Options().apply {
                inSampleSize = sample
            }

            return BitmapFactory.decodeByteArray(
                bytes, 0, bytes.size, options
            ) ?: error("Evidence image could not be decoded")
        } finally {
            connection.disconnect()
        }
    }

    /**
     * Request a fresh, inspection-scoped video evidence grant.
     *
     * This method does not download video bytes. It validates the
     * signed S3 URL before handing it to the playback activity.
     *
     * Never call on the Android main thread or log the returned URL.
     */
    fun loadEvidenceVideoUrl(
        context: Context,
        inspectionId: String,
        findingId: String
    ): String {
        check(Looper.myLooper() != Looper.getMainLooper()) {
            "Video grant must load off the UI thread"
        }

        val session = TvDeviceSessionStore.load(context)
            ?: throw SecurityException("TV pairing required")

        require(
            UUID.fromString(inspectionId).toString() == inspectionId &&
                session.inspectionId == inspectionId
        ) {
            "TV video inspection scope mismatch"
        }

        require(Regex("[0-9a-f]{32}").matches(findingId)) {
            "Invalid video finding identifier"
        }

        val path = (
            "/api/tv/inspections/$inspectionId/" +
                "findings/$findingId/video-url"
        )

        // Existing getJson uses HTTPS, the restricted device
        // token, bounded JSON responses and no redirects.
        val grant = getJson(context, path)

        val expires = grant.getInt("expires_in_seconds")

        require(expires in 1..120) {
            "Unexpected video grant lifetime"
        }

        val url = grant.getString("url")

        val parsed = try {
            URI(url)
        } catch (_: Exception) {
            throw IllegalArgumentException(
                "Invalid video evidence URL"
            )
        }

        val bucket = "rentready-vision-dev-081087819788"
        val host = parsed.host?.lowercase(Locale.ROOT) ?: ""

        // Only the two expected S3 virtual-hosted forms.
        val approvedHost = host in setOf(
            "$bucket.s3.us-west-2.amazonaws.com",
            "$bucket.s3.amazonaws.com"
        )

        val approvedPaths = setOf(
            "/rentready/inspections/$inspectionId/" +
                "evidence/tv-clips/$findingId.mp4",
            "/inspections/$inspectionId/" +
                "evidence/tv-clips/$findingId.mp4"
        )

        require(
            parsed.scheme == "https" &&
                approvedHost &&
                parsed.rawUserInfo == null &&
                parsed.port in listOf(-1, 443) &&
                parsed.rawFragment == null &&
                parsed.rawPath in approvedPaths
        ) {
            "Untrusted video evidence location"
        }

        val parts = parsed.rawQuery?.split("&")
            ?: emptyList()

        val parameters = mutableMapOf<String, String>()

        for (part in parts) {
            val separator = part.indexOf("=")

            require(separator > 0) {
                "Malformed video grant query"
            }

            val name = part.substring(0, separator)
            val value = part.substring(separator + 1)

            require(
                value.isNotEmpty() &&
                    parameters.put(name, value) == null
            ) {
                "Invalid video grant parameters"
            }
        }

        require(
            parameters["X-Amz-Algorithm"] ==
                "AWS4-HMAC-SHA256" &&
                parameters["X-Amz-Expires"] ==
                    expires.toString() &&
                parameters["X-Amz-SignedHeaders"] == "host" &&
                parameters["X-Amz-Credential"]
                    ?.isNotBlank() == true &&
                parameters["X-Amz-Date"]
                    ?.matches(
                        Regex("[0-9]{8}T[0-9]{6}Z")
                    ) == true &&
                parameters["X-Amz-Signature"]
                    ?.matches(
                        Regex("[0-9a-fA-F]{64}")
                    ) == true
        ) {
            "Unsigned or invalid video evidence grant"
        }

        // A short-lived bearer URL: do not persist or log it.
        return url
    }

    private fun optionalText(
        value: JSONObject,
        name: String
    ): String? {
        if (value.isNull(name)) return null

        return value.optString(name).trim()
            .takeIf { it.isNotEmpty() }
    }

    fun load(context: Context): TvInspection {
        check(Looper.myLooper() != Looper.getMainLooper()) {
            "TV HTTP requests must run off the UI thread"
        }

        val deviceSession = TvDeviceSessionStore.load(context)
            ?: throw SecurityException("TV pairing required")

        // Discover only the inspection approved for this device.
        val listing = getJson(
            context, "/api/tv/inspections"
        )
        Log.i("RentReadyTV", "Stage 1: inspection list received")
        val cards = listing.getJSONArray("inspections")

        require(cards.length() == 1) {
            "Expected exactly one approved TV inspection"
        }

        val card = cards.getJSONObject(0)
        val inspectionId = card.getString("id")

        require(UUID.fromString(inspectionId).toString() == inspectionId) {
            "Invalid TV inspection identifier"
        }

        require(inspectionId == deviceSession.inspectionId) {
            "Device session inspection scope mismatch"
        }

        val prefix = "/api/tv/inspections/$inspectionId"

        val overview = getJson(context, prefix)
        Log.i("RentReadyTV", "Stage 2: overview received")
        val roomResponse = getJson(context, "$prefix/rooms")
        Log.i("RentReadyTV", "Stage 3: rooms received")
        val findingResponse = getJson(context, "$prefix/findings")
        Log.i("RentReadyTV", "Stage 4: findings received")
        val briefingResponse = getJson(context, "$prefix/briefing")
        Log.i("RentReadyTV", "Stage 5: briefing received")

        require(
            overview.getString("id") == inspectionId &&
                overview.getString("status") == "COMPLETE" &&
                card.getString("id") == inspectionId
        ) {
            "TV inspection mismatch"
        }

        require(
            roomResponse.getString("inspection_id") == inspectionId &&
                findingResponse.getString("inspection_id") == inspectionId &&
                briefingResponse.getString("inspection_id") == inspectionId
        ) {
            "Cross-inspection response rejected"
        }

        val roomsJson = roomResponse.getJSONArray("rooms")
        val rooms = mutableListOf<TvRoom>()
        val findingToRoom = mutableMapOf<String, String>()

        for (index in 0 until roomsJson.length()) {
            val item = roomsJson.getJSONObject(index)

            val id = item.getString("id")
            val name = item.getString("name")

            require(id.isNotBlank() && name.isNotBlank()) {
                "Invalid TV room"
            }

            require(rooms.none { it.id == id }) {
                "Duplicate TV room"
            }

            rooms.add(TvRoom(id = id, name = name))

            val ids = item.getJSONArray("finding_ids")

            require(ids.length() == item.getInt("finding_count")) {
                "Room finding count mismatch"
            }

            for (position in 0 until ids.length()) {
                val findingId = ids.getString(position)

                require(
                    findingToRoom.put(findingId, id) == null
                ) {
                    "Finding assigned to multiple rooms"
                }
            }
        }

        val findingsJson = findingResponse.getJSONArray("findings")
        val findings = mutableListOf<TvFinding>()

        for (index in 0 until findingsJson.length()) {
            val item = findingsJson.getJSONObject(index)

            require(item.getString("inspection_id") == inspectionId) {
                "Finding inspection mismatch"
            }

            val id = item.getString("id")
            val roomId = findingToRoom[id]

            require(roomId != null) {
                "Finding has no approved room"
            }

            require(findings.none { it.id == id }) {
                "Duplicate TV finding"
            }

            val severity = item.getString("severity")
                .uppercase(Locale.ROOT)

            require(
                severity in setOf(
                    "HIGH", "MEDIUM", "LOW", "UNKNOWN"
                )
            ) {
                "Invalid finding severity"
            }

            val confidence = if (item.isNull("confidence")) {
                null
            } else {
                item.getDouble("confidence").also {
                    require(it.isFinite() && it in 0.0..1.0)
                }
            }

            val timestamp = if (
                item.isNull("timestamp_seconds")
            ) {
                null
            } else {
                item.getDouble("timestamp_seconds").let {
                    require(
                        it.isFinite() &&
                            it >= 0.0 &&
                            it <= Int.MAX_VALUE.toDouble()
                    )
                    it.toInt()
                }
            }

            findings.add(
                TvFinding(
                    id = id,
                    roomId = roomId,
                    title = item.getString("title"),
                    severity = severity,
                    confidence = confidence,
                    timestampSeconds = timestamp,
                    description = optionalText(
                        item, "description"
                    ) ?: "Description not available"
                )
            )
        }

        require(findings.size == findingToRoom.size) {
            "Room and finding relationships do not match"
        }

        require(
            overview.getInt("finding_count") == findings.size &&
                card.getInt("finding_count") == findings.size
        ) {
            "Inspection finding totals do not match"
        }

        val severityCounts = overview.getJSONObject("severity_counts")

        for (severity in listOf("HIGH", "MEDIUM", "LOW", "UNKNOWN")) {
            require(
                findings.count { it.severity == severity } ==
                    severityCounts.getInt(
                        severity.lowercase(Locale.ROOT)
                    )
            ) {
                "Severity total mismatch"
            }
        }

        val priorityId = optionalText(
            briefingResponse, "priority_finding_id"
        )

        // This five-screen prototype expects an actionable priority.
        // A future version will also handle reports without findings.
        require(priorityId != null) {
            "TV briefing has no priority finding"
        }

        val priorityFinding = findings.firstOrNull {
            it.id == priorityId
        } ?: error("Unknown briefing priority finding")

        val headline = briefingResponse.getString("headline")
        val action = optionalText(
            briefingResponse, "recommended_action"
        ) ?: "Recommended action unavailable; review the finding."

        val disclaimer = optionalText(
            briefingResponse, "disclaimer"
        ) ?: "Findings require human review."

        val inspection = TvInspection(
            propertyId = inspectionId,
            propertyName = overview.getString("property_name"),
            status = "COMPLETE",
            rooms = rooms,
            findings = findings,
            evidence = TvEvidence(
                mode = "LOCAL_PLACEHOLDER",
                imageAvailable = false,
                videoAvailable = false
            ),
            briefing = TvBriefing(
                title = "Rental Readiness Briefing",
                headline = headline,
                priorityRoomId = priorityFinding.roomId,
                priorityFindingId = priorityId,
                priorityAction = action,
                secondaryMessage = disclaimer
            )
        )

        Log.i("RentReadyTV", "Stage 6: TV model constructed")
        return inspection
    }
}
