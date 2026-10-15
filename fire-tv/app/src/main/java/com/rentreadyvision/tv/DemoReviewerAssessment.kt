package com.rentreadyvision.tv

// Human-supplied assessment of one fixed hackathon demonstration.
// Never confuse this with detector or Bedrock-generated output.
internal enum class DemoReviewStatus {
    CONFIRMED,
    FALSE_POSITIVE
}

internal object DemoReviewerAssessment {
    private const val INSPECTION_ID =
        "b2054cf1-2401-44df-b675-d01d28acffa9"

    private val expectedCounts = mapOf(
        "bedroom" to 2,
        "bedroom_2" to 1,
        "garage" to 4,
        "kitchen" to 2,
        "living_room" to 2,
        "bathroom_2" to 1
    )

    private val anchors = mapOf(
        "95d16629a02c5abf2bb4b3510e15e073" to "bedroom",
        "555f0443603ef3e57caaace06ea4bed5" to "bedroom_2",
        "877eec22117f6f9508a087d46ed59e43" to "garage",
        "c8ee6b7a97fca8b65ffba5192fd62ac8" to "garage",
        "3dbbfc4ec5c9004a5d82ab104560692f" to "kitchen",
        "92f434406e0a9a5d67d0061ab7f4b268" to "bathroom_2"
    )

    fun applies(inspection: TvInspection): Boolean {
        if (
            inspection.propertyId != INSPECTION_ID ||
            inspection.propertyName != "Demo House" ||
            inspection.findings.size != 12
        ) return false

        val counts = inspection.findings
            .groupingBy { it.roomId }
            .eachCount()

        if (counts != expectedCounts) return false

        return anchors.all { (id, room) ->
            inspection.findings.any {
                it.id == id && it.roomId == room
            }
        }
    }

    fun statusFor(
        inspection: TvInspection,
        finding: TvFinding
    ): DemoReviewStatus? {
        if (!applies(inspection)) return null

        return when (finding.roomId) {
            "garage", "bedroom_2" -> DemoReviewStatus.CONFIRMED
            else -> DemoReviewStatus.FALSE_POSITIVE
        }
    }

    fun featured(inspection: TvInspection): List<TvFinding> {
        if (!applies(inspection)) return emptyList()

        return listOf(
            "877eec22117f6f9508a087d46ed59e43",
            "555f0443603ef3e57caaace06ea4bed5"
        ).mapNotNull { id ->
            inspection.findings.firstOrNull { it.id == id }
        }
    }
}
