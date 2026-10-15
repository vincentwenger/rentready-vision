package com.rentreadyvision.tv

data class TvBedrockPriorityFinding(
    val findingId: String,
    val reason: String,
    val recommendedAction: String
)

data class TvBedrockBriefing(
    val headline: String,
    val priorities: List<TvBedrockPriorityFinding>,
    val disclaimer: String
)
