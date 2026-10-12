package com.rentreadyvision.tv

import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import android.view.Gravity
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.FragmentActivity

class MainActivity : FragmentActivity() {

    private lateinit var root: FrameLayout
    private var showingDemo = false
    private var modernBackCallback: OnBackInvokedCallback? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContentView(R.layout.activity_main)
        root = findViewById(R.id.main_browse_fragment)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val callback = OnBackInvokedCallback {
                if (showingDemo) {
                    showWelcome()
                } else {
                    finish()
                }
            }

            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                callback
            )

            modernBackCallback = callback
        }

        // Remove a restored template fragment, if present.
        val oldFragment =
            supportFragmentManager.findFragmentById(
                R.id.main_browse_fragment
            )

        if (oldFragment != null) {
            supportFragmentManager.beginTransaction()
                .remove(oldFragment)
                .commitNow()
        }

        showWelcome()
    }

    override fun onDestroy() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            modernBackCallback?.let {
                onBackInvokedDispatcher.unregisterOnBackInvokedCallback(it)
            }
            modernBackCallback = null
        }

        super.onDestroy()
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onBackPressed() {
        if (showingDemo) {
            showWelcome()
        } else {
            super.onBackPressed()
        }
    }

    private fun dp(value: Int): Int {
        return (value * resources.displayMetrics.density + 0.5f).toInt()
    }

    private fun buttonBackground(focused: Boolean): GradientDrawable {
        return GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(14).toFloat()

            setColor(
                if (focused) Color.rgb(36, 90, 150)
                else Color.rgb(35, 55, 80)
            )

            setStroke(
                dp(2),
                if (focused) Color.rgb(108, 181, 255)
                else Color.rgb(77, 104, 135)
            )
        }
    }

    private fun renderScreen(
        title: String,
        subtitle: String,
        buttonLabel: String,
        onSelect: () -> Unit
    ) {
        root.removeAllViews()
        root.setBackgroundColor(Color.rgb(16, 28, 48))

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(48), dp(48), dp(48), dp(48))
        }

        val heading = TextView(this).apply {
            text = title
            textSize = 42f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
        }

        content.addView(heading)

        val description = TextView(this).apply {
            text = subtitle
            textSize = 23f
            setTextColor(Color.rgb(195, 213, 239))
            gravity = Gravity.CENTER
        }

        val descriptionParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply {
            topMargin = dp(24)
            bottomMargin = dp(48)
        }

        content.addView(description, descriptionParams)

        val actionButton = Button(this).apply {
            text = buttonLabel
            textSize = 20f
            isAllCaps = false

            setTextColor(Color.WHITE)
            setPadding(dp(32), dp(16), dp(32), dp(16))

            minWidth = dp(320)
            minHeight = dp(72)

            isFocusable = true
            isFocusableInTouchMode = true

            backgroundTintList = null
            background = buttonBackground(false)

            setOnFocusChangeListener { view, focused ->
                view.background = buttonBackground(focused)
                view.scaleX = if (focused) 1.06f else 1f
                view.scaleY = if (focused) 1.06f else 1f
            }

            setOnClickListener {
                onSelect()
            }
        }

        content.addView(actionButton)

        root.addView(
            content,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )

        actionButton.requestFocus()
    }

    private fun showWelcome() {
        showingDemo = false

        renderScreen(
            title = "RENTREADY VISION",
            subtitle = "AI Property Inspection",
            buttonLabel = "Open Demo Inspection"
        ) {
            showDemo()
        }
    }

    private fun showDemo() {
        showingDemo = true

        renderScreen(
            title = "Demo Inspection",
            subtitle = "Local demonstration placeholder - no backend connected",
            buttonLabel = "Back to Home"
        ) {
            showWelcome()
        }
    }
}