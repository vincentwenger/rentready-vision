package com.rentreadyvision.tv

import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import androidx.fragment.app.FragmentActivity

class MainActivity : FragmentActivity() {

    private enum class Screen {
        INSPECTIONS,
        OVERVIEW,
        ROOM,
        FINDING,
        BRIEFING
    }

    private data class Page(
        val screen: Screen,
        val roomId: String? = null,
        val findingId: String? = null
    )

    private lateinit var root: FrameLayout
    private lateinit var inspection: TvInspection

    private var currentPage = Page(Screen.INSPECTIONS)
    private val history = mutableListOf<Page>()
    private var backCallback: OnBackInvokedCallback? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContentView(R.layout.activity_main)
        root = findViewById(R.id.main_browse_fragment)

        // Remove any old Leanback sample fragment.
        supportFragmentManager
            .findFragmentById(R.id.main_browse_fragment)
            ?.let { fragment ->
                supportFragmentManager.beginTransaction()
                    .remove(fragment)
                    .commitNow()
            }

        // Only bundled local JSON is loaded.
        inspection = TvInspection.load(this)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val callback = OnBackInvokedCallback {
                navigateBack()
            }

            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                callback
            )
            backCallback = callback
        }

        render()
    }

    override fun onDestroy() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            backCallback?.let {
                onBackInvokedDispatcher.unregisterOnBackInvokedCallback(it)
            }
            backCallback = null
        }
        super.onDestroy()
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onBackPressed() {
        navigateBack()
    }

    private fun navigateTo(page: Page) {
        history.add(currentPage)
        currentPage = page
        render()
    }

    private fun navigateBack() {
        if (history.isNotEmpty()) {
            currentPage = history.removeAt(history.lastIndex)
            render()
        } else {
            finish()
        }
    }

    private fun dp(value: Int): Int {
        return (value * resources.displayMetrics.density + 0.5f).toInt()
    }

    private fun focusBackground(focused: Boolean): GradientDrawable {
        return GradientDrawable().apply {
            cornerRadius = dp(12).toFloat()
            setColor(
                if (focused) Color.rgb(38, 89, 148)
                else Color.rgb(35, 52, 75)
            )
            setStroke(
                dp(2),
                if (focused) Color.rgb(105, 184, 255)
                else Color.rgb(65, 86, 111)
            )
        }
    }

    private fun addText(
        column: LinearLayout,
        value: String,
        size: Float,
        bottom: Int = 18,
        bold: Boolean = false,
        tint: Int = Color.WHITE
    ) {
        val view = TextView(this).apply {
            text = value
            textSize = size
            setTextColor(tint)
            typeface = if (bold) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
        }

        column.addView(
            view,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(bottom)
            }
        )
    }

    private fun addAction(
        column: LinearLayout,
        label: String,
        action: () -> Unit
    ): TextView {
        val view = TextView(this).apply {
            text = label
            textSize = 22f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(24), dp(16), dp(24), dp(16))
            minHeight = dp(70)

            isFocusable = true
            isFocusableInTouchMode = true
            isClickable = true

            background = focusBackground(false)

            setOnFocusChangeListener { item, focused ->
                item.background = focusBackground(focused)
                item.scaleX = if (focused) 1.015f else 1f
                item.scaleY = if (focused) 1.015f else 1f
            }

            setOnClickListener {
                action()
            }
        }

        column.addView(
            view,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = dp(12)
            }
        )

        return view
    }

    private fun render() {
        root.removeAllViews()
        root.setBackgroundColor(Color.rgb(16, 28, 48))

        val scroll = ScrollView(this).apply {
            isFillViewport = true
            isFocusable = false
        }

        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(56), dp(42), dp(56), dp(60))
        }

        scroll.addView(
            column,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT
            )
        )

        root.addView(
            scroll,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )

        val firstAction = when (currentPage.screen) {
            Screen.INSPECTIONS -> showInspections(column)
            Screen.OVERVIEW -> showOverview(column)
            Screen.ROOM -> showRoom(column)
            Screen.FINDING -> showFinding(column)
            Screen.BRIEFING -> showBriefing(column)
        }

        // TV remote focus: no mouse required.
        firstAction.post {
            firstAction.requestFocus()
        }
    }

    private fun showInspections(column: LinearLayout): TextView {
        addText(column, "RENTREADY VISION", 40f, 28, true)
        addText(column, "INSPECTIONS", 26f, 30, true)

        return addAction(
            column,
            "${inspection.propertyName}\n" +
                "${inspection.status}\n" +
                "${inspection.findings.size} findings\n\n" +
                "VIEW INSPECTION"
        ) {
            navigateTo(Page(Screen.OVERVIEW))
        }
    }

    private fun showOverview(column: LinearLayout): TextView {
        addText(
            column,
            inspection.propertyName.uppercase(),
            38f,
            8,
            true
        )

        addText(
            column,
            "AI PROPERTY INSPECTION",
            20f,
            28,
            tint = Color.LTGRAY
        )

        addText(
            column,
            "${inspection.findings.size} potential findings",
            27f,
            20,
            true
        )

        for (severity in listOf("HIGH", "MEDIUM", "LOW")) {
            addText(
                column,
                "$severity       ${inspection.severityCount(severity)}",
                21f,
                9
            )
        }

        addText(column, "ROOMS", 27f, 18, true)

        var first: TextView? = null

        for (room in inspection.rooms) {
            val count = inspection.findingsInRoom(room.id).size
            val summary = if (count == 0) "Clear" else if (count == 1) "1 finding" else "$count findings"

            val action = addAction(
                column,
                "${room.name}     $summary"
            ) {
                navigateTo(Page(Screen.ROOM, roomId = room.id))
            }

            if (first == null) first = action
        }

        val briefing = addAction(column, "VIEW PROPERTY BRIEFING") {
            navigateTo(Page(Screen.BRIEFING))
        }

        return first ?: briefing
    }

    private fun showRoom(column: LinearLayout): TextView {
        val roomId = requireNotNull(currentPage.roomId)
        val room = inspection.findRoom(roomId)
        val findings = inspection.findingsInRoom(roomId)

        addText(column, room.name.uppercase(), 38f, 18, true)

        addText(
            column,
            if (findings.isEmpty()) "CLEAR - NO POTENTIAL FINDINGS"
            else if (findings.size == 1) "1 POTENTIAL FINDING" else "${findings.size} POTENTIAL FINDINGS",
            23f,
            28
        )

        if (findings.isEmpty()) {
            return addAction(column, "BACK TO PROPERTY") {
                navigateBack()
            }
        }

        var first: TextView? = null

        for (finding in findings) {
            val action = addAction(
                column,
                "${finding.title}\n${finding.severity}"
            ) {
                navigateTo(
                    Page(
                        Screen.FINDING,
                        roomId = roomId,
                        findingId = finding.id
                    )
                )
            }

            if (first == null) first = action
        }

        return requireNotNull(first)
    }

    private fun showFinding(column: LinearLayout): TextView {
        val roomId = requireNotNull(currentPage.roomId)
        val findingId = requireNotNull(currentPage.findingId)

        val room = inspection.findRoom(roomId)
        val finding = inspection.findFinding(findingId)

        addText(column, room.name.uppercase(), 28f, 16, true)
        addText(column, finding.title, 32f, 26, true)

        addText(
            column,
            "Severity       ${finding.severity}",
            22f,
            12
        )

        addText(
            column,
            "Confidence     ${finding.confidencePercent()}%",
            22f,
            24
        )

        val evidenceBox = FrameLayout(this).apply {
            background = GradientDrawable().apply {
                setColor(Color.rgb(30, 44, 65))
                cornerRadius = dp(12).toFloat()
                setStroke(dp(1), Color.rgb(85, 105, 135))
            }

            addView(
                TextView(this@MainActivity).apply {
                    text = "LOCAL EVIDENCE PLACEHOLDER\nNo image bundled"
                    textSize = 20f
                    setTextColor(Color.LTGRAY)
                    gravity = Gravity.CENTER
                },
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.MATCH_PARENT
                )
            )
        }

        column.addView(
            evidenceBox,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(170)
            ).apply {
                bottomMargin = dp(24)
            }
        )

        addText(
            column,
            "Detected at ${finding.timestampLabel()}",
            20f,
            20
        )

        addText(column, finding.description, 21f, 26)

        return addAction(column, "PLAY EVIDENCE") {
            Toast.makeText(
                this,
                "Evidence video unavailable in this offline demo",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    private fun showBriefing(column: LinearLayout): TextView {
        val briefing = inspection.briefing
        val room = inspection.findRoom(briefing.priorityRoomId)

        addText(
            column,
            briefing.title.uppercase(),
            35f,
            32,
            true
        )

        addText(column, briefing.headline, 28f, 30, true)
        addText(column, room.name, 25f, 12, true)
        addText(column, briefing.priorityAction, 22f, 30)

        addText(
            column,
            briefing.secondaryMessage,
            22f,
            26
        )

        addText(
            column,
            "Synthetic demo only - priorities require human confirmation.",
            17f,
            30,
            tint = Color.LTGRAY
        )

        return addAction(column, "VIEW PRIORITY FINDINGS") {
            navigateTo(
                Page(
                    Screen.ROOM,
                    roomId = briefing.priorityRoomId
                )
            )
        }
    }
}
