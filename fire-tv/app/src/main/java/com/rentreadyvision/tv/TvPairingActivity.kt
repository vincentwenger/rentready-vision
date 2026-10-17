package com.rentreadyvision.tv

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.GridLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * Remote-controlled pairing screen.
 *
 * No operator credentials, raw device tokens, or signed S3 URLs
 * are displayed or logged.
 */
class TvPairingActivity : Activity() {
    private val alphabet =
        "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    private val entered = StringBuilder()
    private val controls = mutableListOf<Button>()

    private lateinit var display: TextView
    private lateinit var status: TextView
    private lateinit var pairButton: Button

    private var busy = false

    private fun dp(value: Int): Int {
        return (
            value * resources.displayMetrics.density + 0.5f
        ).toInt()
    }

    private fun label(
        value: String,
        size: Float,
        color: Int = Color.WHITE
    ): TextView {
        return TextView(this).apply {
            text = value
            textSize = size
            setTextColor(color)
            gravity = Gravity.CENTER
            setPadding(0, dp(4), 0, dp(12))
        }
    }

    private fun button(
        value: String,
        action: () -> Unit
    ): Button {
        return Button(this).apply {
            text = value
            isAllCaps = false
            isFocusable = true
            setOnClickListener { action() }
            controls.add(this)
        }
    }

    private fun updateDisplay() {
        val padded = entered.toString().padEnd(10, '_')

        display.text = (
            padded.substring(0, 5) + "-" +
                padded.substring(5, 10)
        )

        pairButton.isEnabled = !busy && entered.length == 10

        for (control in controls) {
            if (control !== pairButton) {
                control.isEnabled = !busy
            }
        }
    }

    private fun addLetter(letter: Char) {
        if (busy || entered.length >= 10) return

        entered.append(letter)
        status.text = "Enter the ten-character code."
        updateDisplay()
    }

    private fun erase() {
        if (busy || entered.isEmpty()) return

        entered.deleteCharAt(entered.length - 1)
        updateDisplay()
    }

    private fun submit() {
        if (busy || entered.length != 10) return

        val raw = entered.toString()
        val code = (
            raw.substring(0, 5) + "-" +
                raw.substring(5, 10)
        )

        busy = true
        status.text = "PAIRING SECURELY..."
        updateDisplay()

        Thread({
            val result = runCatching {
                val session = TvPairingClient.redeem(code)
                TvDeviceSessionStore.save(
                    applicationContext,
                    session
                )
            }

            runOnUiThread {
                if (isFinishing || isDestroyed) {
                    return@runOnUiThread
                }

                busy = false

                result.onSuccess {
                    entered.clear()
                    setResult(RESULT_OK)
                    finish()
                }.onFailure { failure ->
                    status.text = if (
                        failure is TvPairingException
                    ) {
                        failure.friendlyMessage
                    } else {
                        "Pairing failed. Check the connection " +
                            "and request a new code if needed."
                    }

                    updateDisplay()
                }
            }
        }, "rentready-secure-tv-pairing").start()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        window.decorView.setBackgroundColor(
            Color.rgb(16, 28, 48)
        )

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(30), dp(15), dp(30), dp(30))
        }

        val scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(content)
        }

        setContentView(scroll)

        content.addView(
            label("RENTREADY VISION", 34f)
        )

        content.addView(
            label("PAIR THIS TV", 26f)
        )

        content.addView(
            label(
                "Enter the code provided by the operator. " +
                    "Standard codes expire after five minutes. Judge demo codes use their stated expiration date.",
                18f,
                Color.LTGRAY
            )
        )

        display = label("_____-_____", 32f).apply {
            letterSpacing = 0.12f
        }
        content.addView(display)

        val grid = GridLayout(this).apply {
            columnCount = 8
        }

        for (letter in alphabet) {
            val control = button(letter.toString()) {
                addLetter(letter)
            }

            grid.addView(
                control,
                GridLayout.LayoutParams().apply {
                    width = dp(108)
                    height = dp(64)
                    setMargins(dp(4), dp(2), dp(4), dp(2))
                }
            )
        }

        content.addView(grid)

        val actions = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }

        val deleteButton = button("DELETE") {
            erase()
        }
        actions.addView(deleteButton)

        val clearButton = button("CLEAR") {
            if (!busy) {
                entered.clear()
                updateDisplay()
            }
        }
        actions.addView(clearButton)

        pairButton = button("PAIR TV") {
            submit()
        }
        actions.addView(pairButton)

        val cancelButton = button("CANCEL") {
            if (!busy) {
                setResult(RESULT_CANCELED)
                finish()
            }
        }
        actions.addView(cancelButton)

        content.addView(actions)

        status = label(
            "Use the remote to select each character.",
            18f,
            Color.LTGRAY
        )
        content.addView(status)

        updateDisplay()

        grid.getChildAt(0)?.requestFocus()
    }
}
