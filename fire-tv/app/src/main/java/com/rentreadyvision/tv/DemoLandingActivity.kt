package com.rentreadyvision.tv

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/** Explicit choice between a local sample and the existing protected live inspection. */
class DemoLandingActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Color.rgb(16, 28, 48))
            setPadding(50, 30, 50, 30)
        }
        fun text(value: String, size: Float, color: Int = Color.WHITE) {
            layout.addView(TextView(this).apply {
                text = value
                textSize = size
                setTextColor(color)
                gravity = Gravity.CENTER
                setPadding(8, 14, 8, 14)
            })
        }
        fun action(label: String, listener: () -> Unit) {
            layout.addView(Button(this).apply {
                text = label
                isAllCaps = false
                isFocusable = true
                textSize = 21f
                setOnClickListener { listener() }
            }, LinearLayout.LayoutParams(700, LinearLayout.LayoutParams.WRAP_CONTENT))
        }
        text("RENTREADY VISION", 42f)
        text("AI Property Inspection for TV", 24f, Color.LTGRAY)
        text("Choose how to explore the application", 20f, Color.LTGRAY)
        action("OPEN DEMO INSPECTION — OFFLINE") {
            startActivity(Intent(this, OfflineDemoActivity::class.java))
        }
        text("Sample images and videos. No sign-in or network required.", 16f, Color.LTGRAY)
        action("OPEN LIVE AWS INSPECTION — PAIRING REQUIRED") {
            startActivity(Intent(this, MainActivity::class.java).apply {
                putExtra("com.rentreadyvision.tv.EXTRA_LIVE_MODE", true)
            })
        }
        text("Live mode retrieves authorized findings and saved Bedrock output.", 16f, Color.LTGRAY)
        setContentView(layout)
        layout.getChildAt(3)?.requestFocus()
    }
}
