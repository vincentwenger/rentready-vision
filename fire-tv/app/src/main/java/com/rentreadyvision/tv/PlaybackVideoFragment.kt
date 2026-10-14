package com.rentreadyvision.tv

import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.leanback.app.VideoSupportFragment
import androidx.leanback.app.VideoSupportFragmentGlueHost
import androidx.leanback.media.MediaPlayerAdapter
import androidx.leanback.media.PlaybackTransportControlGlue
import androidx.leanback.widget.PlaybackControlsRow

/**
 * Plays only authenticated RentReady Vision evidence.
 *
 * The source URL is fetched off the UI thread, used in memory,
 * and never persisted, logged or passed through an Intent.
 */
class PlaybackVideoFragment : VideoSupportFragment() {

    private lateinit var transportGlue:
        PlaybackTransportControlGlue<MediaPlayerAdapter>

    private var requestGeneration = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val owner = requireActivity()
        val inspectionId = owner.intent.getStringExtra(
            PlaybackActivity.EXTRA_INSPECTION_ID
        )
        val findingId = owner.intent.getStringExtra(
            PlaybackActivity.EXTRA_FINDING_ID
        )

        if (inspectionId == null || findingId == null) {
            owner.finish()
            return
        }

        val title = owner.intent.getStringExtra(
            PlaybackActivity.EXTRA_TITLE
        )?.take(120) ?: "Video evidence"

        val playerAdapter = MediaPlayerAdapter(requireContext())
        playerAdapter.setRepeatAction(
            PlaybackControlsRow.RepeatAction.INDEX_NONE
        )

        transportGlue = PlaybackTransportControlGlue(
            requireActivity(),
            playerAdapter
        )

        transportGlue.host = VideoSupportFragmentGlueHost(this)
        transportGlue.title = title
        transportGlue.subtitle = "Inspection video evidence"
        transportGlue.playWhenPrepared()

        val generation = ++requestGeneration
        val appContext = owner.applicationContext

        // Signed grants are obtained only when playback is opened.
        Thread({
            val result = runCatching {
                TvApiClient.loadEvidenceVideoUrl(
                    appContext,
                    inspectionId,
                    findingId
                )
            }

            owner.runOnUiThread {
                if (
                    generation != requestGeneration ||
                    !isAdded ||
                    owner.isFinishing ||
                    owner.isDestroyed
                ) {
                    return@runOnUiThread
                }

                result.onSuccess { signedUrl ->
                    // Pass the validated HTTPS URI directly to
                    // Android's media player, never to a log.
                    runCatching {
                        playerAdapter.setDataSource(
                            Uri.parse(signedUrl)
                        )
                    }.onFailure {
                        showUnavailable()
                    }
                }.onFailure {
                    showUnavailable()
                }
            }
        }, "rentready-tv-video-grant").start()
    }

    private fun showUnavailable() {
        val owner = activity ?: return

        Toast.makeText(
            owner,
            "Video evidence could not be loaded",
            Toast.LENGTH_LONG
        ).show()

        owner.finish()
    }

    override fun onPause() {
        if (::transportGlue.isInitialized) {
            transportGlue.pause()
        }
        super.onPause()
    }

    override fun onDestroy() {
        // Invalidate any outstanding background grant request.
        requestGeneration += 1
        super.onDestroy()
    }
}
