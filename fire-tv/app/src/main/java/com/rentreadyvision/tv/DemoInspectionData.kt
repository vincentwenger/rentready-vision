package com.rentreadyvision.tv

import android.content.Context
import org.json.JSONObject

data class TvRoom(
    val id: String,
    val name: String
)

data class TvFinding(
    val id: String,
    val roomId: String,
    val title: String,
    val severity: String,
    val confidence: Double?,
    val timestampSeconds: Int?,
    val description: String
) {
    fun timestampLabel(): String {
        val timestamp = timestampSeconds ?: return "Not available"
        val hours = timestamp / 3600
        val minutes = (timestamp % 3600) / 60
        val seconds = timestamp % 60
        return "%02d:%02d:%02d".format(hours, minutes, seconds)
    }

    fun confidencePercent(): Int? {
        return confidence?.let { (it * 100).toInt() }
    }
}

data class TvEvidence(
    val mode: String,
    val imageAvailable: Boolean,
    val videoAvailable: Boolean
)

data class TvBriefing(
    val title: String,
    val headline: String,
    val priorityRoomId: String,
    val priorityFindingId: String,
    val priorityAction: String,
    val secondaryMessage: String
)

data class TvInspection(
    val propertyId: String,
    val propertyName: String,
    val status: String,
    val rooms: List<TvRoom>,
    val findings: List<TvFinding>,
    val evidence: TvEvidence,
    val briefing: TvBriefing
) {
    fun findingsInRoom(roomId: String): List<TvFinding> {
        return findings.filter { it.roomId == roomId }
    }

    fun severityCount(severity: String): Int {
        return findings.count { it.severity == severity }
    }

    fun findRoom(roomId: String): TvRoom {
        return rooms.first { it.id == roomId }
    }

    fun findFinding(findingId: String): TvFinding {
        return findings.first { it.id == findingId }
    }

    companion object {
        fun load(context: Context): TvInspection {
            val raw = context.assets
                .open("mozart_house_demo.json")
                .bufferedReader(Charsets.UTF_8)
                .use { it.readText() }

            val root = JSONObject(raw)

            require(root.getInt("schemaVersion") == 1) {
                "Unsupported inspection schema"
            }

            require(root.getBoolean("demoOnly")) {
                "This prototype accepts only demo data"
            }

            val property = root.getJSONObject("property")

            val roomArray = root.getJSONArray("rooms")
            val rooms = (0 until roomArray.length()).map { index ->
                val item = roomArray.getJSONObject(index)

                TvRoom(
                    id = item.getString("id"),
                    name = item.getString("name")
                )
            }

            val findingArray = root.getJSONArray("findings")
            val findings = (0 until findingArray.length()).map { index ->
                val item = findingArray.getJSONObject(index)

                TvFinding(
                    id = item.getString("id"),
                    roomId = item.getString("roomId"),
                    title = item.getString("title"),
                    severity = item.getString("severity"),
                    confidence = item.getDouble("confidence"),
                    timestampSeconds = item.getInt("timestampSeconds"),
                    description = item.getString("description")
                )
            }

            val evidenceObject = root.getJSONObject("evidence")

            val evidence = TvEvidence(
                mode = evidenceObject.getString("mode"),
                imageAvailable = evidenceObject.getBoolean("imageAvailable"),
                videoAvailable = evidenceObject.getBoolean("videoAvailable")
            )

            val briefingObject = root.getJSONObject("briefing")

            val briefing = TvBriefing(
                title = briefingObject.getString("title"),
                headline = briefingObject.getString("headline"),
                priorityRoomId = briefingObject.getString("priorityRoomId"),
                priorityFindingId = briefingObject.getString("priorityFindingId"),
                priorityAction = briefingObject.getString("priorityAction"),
                secondaryMessage = briefingObject.getString("secondaryMessage")
            )

            val inspection = TvInspection(
                propertyId = property.getString("id"),
                propertyName = property.getString("name"),
                status = property.getString("status"),
                rooms = rooms,
                findings = findings,
                evidence = evidence,
                briefing = briefing
            )

            val roomIds = rooms.map { it.id }.toSet()
            val findingIds = findings.map { it.id }.toSet()

            require(rooms.size == roomIds.size) {
                "Duplicate room IDs"
            }

            require(findings.size == findingIds.size) {
                "Duplicate finding IDs"
            }

            require(findings.all {
                it.roomId in roomIds &&
                    it.severity in setOf("HIGH", "MEDIUM", "LOW") &&
                    (it.confidence == null || it.confidence in 0.0..1.0) &&
                    (it.timestampSeconds == null || it.timestampSeconds >= 0)
            }) {
                "Invalid finding metadata"
            }

            require(briefing.priorityRoomId in roomIds) {
                "Invalid briefing room"
            }

            require(findings.any {
                it.id == briefing.priorityFindingId &&
                    it.roomId == briefing.priorityRoomId
            }) {
                "Invalid briefing finding reference"
            }

            require(evidence.mode == "LOCAL_PLACEHOLDER") {
                "Only local placeholder evidence is supported"
            }

            return inspection
        }
    }
}
