package com.rentreadyvision.tv

import android.app.Activity
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.VideoView

/** Plays only the three bundled, synthetic demonstration clips. */
class OfflineVideoActivity : Activity() {
    companion object {
        const val EXTRA_INDEX = "com.rentreadyvision.tv.OFFLINE_EXAMPLE_INDEX"
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val videos = intArrayOf(
            R.raw.offline_garage_crack,
            R.raw.offline_garage_stain,
            R.raw.offline_bedroom_wall
        )
        val index = intent.getIntExtra(EXTRA_INDEX, -1)
        if (index !in videos.indices) {
            finish()
            return
        }
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setBackgroundColor(Color.rgb(16, 28, 48))
            setPadding(24, 14, 24, 14)
        }
        layout.addView(TextView(this).apply {
            text = "LOCAL VIDEO DEMO — SYNTHETIC, NOT ACTUAL PROPERTY FOOTAGE"
            textSize = 19f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
        })
        val video = VideoView(this)
        layout.addView(video, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            480, 1f
        ))
        val controls = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        fun button(name: String, handler: () -> Unit) {
            controls.addView(Button(this).apply {
                text = name
                isAllCaps = false
                isFocusable = true
                setOnClickListener { handler() }
            })
        }
        button("PLAY / REPLAY") { video.seekTo(0); video.start() }
        button("PAUSE") { video.pause() }
        button("BACK TO FINDING") { finish() }
        layout.addView(controls)
        setContentView(layout)
        video.setOnPreparedListener { video.start() }
        video.setOnErrorListener { _, _, _ ->
            android.widget.Toast.makeText(this, "Offline sample video unavailable", android.widget.Toast.LENGTH_LONG).show()
            true
        }
        video.setVideoURI(Uri.parse("android.resource://$packageName/${videos[index]}"))
        controls.getChildAt(0)?.requestFocus()
    }
    override fun onPause() {
        super.onPause()
        // Offline demo requires no background playback.
    }
}
