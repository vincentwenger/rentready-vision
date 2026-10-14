package com.rentreadyvision.tv

import android.os.Bundle
import androidx.fragment.app.FragmentActivity
import java.util.UUID

/**
 * Non-exported, inspection-scoped evidence playback.
 *
 * The Intent carries only finding identity and display text.
 * It must NEVER contain a signed S3 URL or API credential.
 */
class PlaybackActivity : FragmentActivity() {

    companion object {
        const val EXTRA_INSPECTION_ID =
            "com.rentreadyvision.tv.EXTRA_INSPECTION_ID"

        const val EXTRA_FINDING_ID =
            "com.rentreadyvision.tv.EXTRA_FINDING_ID"

        const val EXTRA_TITLE =
            "com.rentreadyvision.tv.EXTRA_VIDEO_TITLE"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val inspectionId = intent.getStringExtra(EXTRA_INSPECTION_ID)
        val findingId = intent.getStringExtra(EXTRA_FINDING_ID)
        val session = TvDeviceSessionStore.load(this)

        val validInspection = inspectionId != null &&
            runCatching {
                UUID.fromString(inspectionId).toString() == inspectionId
            }.getOrDefault(false)

        if (
            !validInspection ||
            session == null ||
            session.inspectionId != inspectionId ||
            findingId == null ||
            !Regex("[0-9a-f]{32}").matches(findingId)
        ) {
            finish()
            return
        }

        if (savedInstanceState == null) {
            supportFragmentManager.beginTransaction()
                .replace(
                    android.R.id.content,
                    PlaybackVideoFragment()
                )
                .commit()
        }
    }
}
