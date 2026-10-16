package com.rentreadyvision.tv

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Standalone sample: no network, S3, pairing, or Bedrock calls. */
class OfflineDemoActivity : Activity() {
    private enum class Page { OVERVIEW, FINDING, IMAGE, BRIEFING }
    private data class Example(
        val room: String,
        val title: String,
        val description: String,
        val image: Int,
        val video: Int
    )
    private val examples = listOf(
        Example("Garage", "Illustrative floor crack", "A drawn surface crack demonstrates how a finding could be reviewed.", R.drawable.offline_garage_crack, R.raw.offline_garage_crack),
        Example("Garage", "Illustrative floor staining", "A simulated patch of staining shows a second reviewable condition.", R.drawable.offline_garage_stain, R.raw.offline_garage_stain),
        Example("Bedroom 2", "Illustrative wall mark", "A synthetic wall mark represents a cosmetic review item.", R.drawable.offline_bedroom_wall, R.raw.offline_bedroom_wall)
    )
    private var page = Page.OVERVIEW
    private var selected = 0
    private var previousFocus: Int = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        render()
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density + 0.5f).toInt()
    private fun render() {
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(16, 28, 48))
            setPadding(dp(32), dp(24), dp(32), dp(30))
        }
        fun label(value: String, size: Float = 19f, color: Int = Color.WHITE) {
            content.addView(TextView(this).apply {
                text = value
                textSize = size
                setTextColor(color)
                setPadding(dp(10), dp(6), dp(10), dp(12))
            })
        }
        val buttons = mutableListOf<Button>()
        fun action(value: String, onClick: () -> Unit) {
            val button = Button(this).apply {
                text = value
                isAllCaps = false
                textSize = 19f
                isFocusable = true
                setOnClickListener { onClick() }
            }
            buttons.add(button)
            content.addView(button, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ))
        }
        fun media(image: Int, height: Int) {
            content.addView(ImageView(this).apply {
                setImageResource(image)
                scaleType = ImageView.ScaleType.FIT_CENTER
                contentDescription = "Synthetic demonstration image"
            }, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(height)
            ))
        }

        label("RENTREADY VISION — OFFLINE DEMO", 29f)
        label("Synthetic sample media. No real property evidence or live model inference.", 16f, Color.LTGRAY)
        when (page) {
            Page.OVERVIEW -> {
                label("DEMO HOUSE  |  3 example findings", 25f)
                label("Use the D-pad to select a finding and see its evidence.")
                examples.forEachIndexed { index, ex ->
                    action("${ex.room} — ${ex.title}") {
                        selected = index
                        previousFocus = index
                        page = Page.FINDING
                        render()
                    }
                }
                action("RENTAL READINESS BRIEFING — SAMPLE") {
                    page = Page.BRIEFING
                    render()
                }
                action("BACK TO START") { finish() }
            }
            Page.FINDING -> {
                val ex = examples[selected]
                label("${ex.room.uppercase()} — ${ex.title}", 25f)
                label(ex.description)
                media(ex.image, 245)
                action("VIEW FULL IMAGE") {
                    page = Page.IMAGE
                    render()
                }
                action("PLAY LOCAL VIDEO EVIDENCE") {
                    startActivity(Intent(this, OfflineVideoActivity::class.java).apply {
                        putExtra(OfflineVideoActivity.EXTRA_INDEX, selected)
                    })
                }
                action("BACK TO FINDINGS") {
                    page = Page.OVERVIEW
                    render()
                }
            }
            Page.IMAGE -> {
                val ex = examples[selected]
                label("SYNTHETIC DEMO IMAGE — ${ex.title}", 24f)
                media(ex.image, 460)
                action("BACK TO FINDING") {
                    page = Page.FINDING
                    render()
                }
            }
            Page.BRIEFING -> {
                label("SAMPLE RENTAL READINESS BRIEFING", 25f)
                label("Illustrative offline summary — not a live or cached Bedrock inference.", 18f, Color.LTGRAY)
                label("1. Garage floor crack: visually review the marked region.")
                label("2. Garage discoloration: verify whether the floor requires cleaning or further inspection.")
                label("3. Bedroom wall mark: consider a cosmetic repair after human review.")
                label("In Live AWS mode, the real saved Bedrock briefing is retrieved through the restricted API.", 17f, Color.LTGRAY)
                action("BACK TO FINDINGS") {
                    page = Page.OVERVIEW
                    render()
                }
            }
        }
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(content)
        }
        setContentView(scroll)
        val focus = if (page == Page.OVERVIEW) previousFocus.coerceIn(0, buttons.lastIndex) else 0
        buttons.getOrNull(focus)?.requestFocus()
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onBackPressed() {
        when (page) {
            Page.OVERVIEW -> finish()
            Page.FINDING -> { page = Page.OVERVIEW; render() }
            Page.IMAGE -> { page = Page.FINDING; render() }
            Page.BRIEFING -> { page = Page.OVERVIEW; render() }
        }
    }
}
