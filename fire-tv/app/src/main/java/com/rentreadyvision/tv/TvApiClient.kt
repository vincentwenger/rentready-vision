package com.rentreadyvision.tv

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Looper
import android.util.Log
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale
import java.util.UUID

/**
 * Development-only client for the loopback Fire TV emulator bridge.
 *
 * No operator API token or AWS credentials are used.
 * Must run on a background thread.
 * A public or production Fire TV app requires separate authentication.
 */
object TvApiClient {

    private const val BASE_URL = "http://127.0.0.1:8765"
    private const val MAX_RESPONSE_BYTES = 1_000_000

    private fun getJson(path: String): JSONObject {
        var lastTransportError: java.io.IOException? = null

        for (attempt in 1..3) {
            try {
                return getJsonOnce(path)
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

    private fun getJsonOnce(path: String): JSONObject {
        require(path.startsWith("/api/tv/")) {
            "Unsupported TV API path"
        }

        val connection = (
            URL(BASE_URL + path).openConnection()
                as HttpURLConnection
        )

        connection.requestMethod = "GET"
        connection.connectTimeout = 5_000
        connection.readTimeout = 10_000
        connection.instanceFollowRedirects = false
        connection.useCaches = false
        connection.setRequestProperty("Accept", "application/json")

        try {
            val status = connection.responseCode

            check(status == 200) {
                "TV bridge unavailable (HTTP $status)"
            }

            val declaredLength = connection.contentLengthLong

            require(
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

            require(bytes.size.toLong() == declaredLength) {
                "Incomplete TV HTTP response"
            }

            return JSONObject(String(bytes, Charsets.UTF_8))
        } finally {
            connection.disconnect()
        }
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
        check(
            (
                context.applicationInfo.flags and
                    ApplicationInfo.FLAG_DEBUGGABLE
            ) != 0
        ) {
            "Local TV bridge is disabled outside debug builds"
        }

        check(Looper.myLooper() != Looper.getMainLooper()) {
            "TV HTTP requests must run off the UI thread"
        }

        // Discover the one explicitly approved inspection.
        val listing = getJson("/api/tv/inspections")
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

        val prefix = "/api/tv/inspections/$inspectionId"

        val overview = getJson(prefix)
        Log.i("RentReadyTV", "Stage 2: overview received")
        val roomResponse = getJson("$prefix/rooms")
        Log.i("RentReadyTV", "Stage 3: rooms received")
        val findingResponse = getJson("$prefix/findings")
        Log.i("RentReadyTV", "Stage 4: findings received")
        val briefingResponse = getJson("$prefix/briefing")
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
