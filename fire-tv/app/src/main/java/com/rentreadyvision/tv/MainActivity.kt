package com.rentreadyvision.tv

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
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
        val findingId: String? = null,
        val focusKey: String? = null
    )

    private lateinit var root: FrameLayout
    private lateinit var inspection: TvInspection

    private var isLoading = false
    private var loadError: String? = null
    private var loadGeneration = 0

    private var bedrockBriefing: TvBedrockBriefing? = null
    private var bedrockLoading = false
    private var bedrockUnavailable = false
    private var bedrockStatusMessage: String? = null
    private var bedrockGeneration = 0

    // Keep at most one real evidence image in memory.
    private var evidenceBitmap: Bitmap? = null
    private var evidenceFindingId: String? = null
    private var evidenceLoading = false
    private var evidenceFailed = false
    private var evidenceGeneration = 0

    private var currentPage = Page(Screen.INSPECTIONS)
    private val history = mutableListOf<Page>()
    private var backCallback: OnBackInvokedCallback? = null

    private val videoInspectionId =
        "b2054cf1-2401-44df-b675-d01d28acffa9"

    private val videoFindingIds = setOf(
        "877eec22117f6f9508a087d46ed59e43",
        "c8ee6b7a97fca8b65ffba5192fd62ac8",
        "555f0443603ef3e57caaace06ea4bed5"
    )

    private var evidenceReturnFocusKey: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // The launcher opens a fully offline sample by default.
        // Explicit live mode keeps the existing protected HTTPS/pairing flow.
        if (!intent.getBooleanExtra(
                "com.rentreadyvision.tv.EXTRA_LIVE_MODE", false
            )) {
            startActivity(Intent(this, DemoLandingActivity::class.java))
            finish()
            return
        }

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

        // Select the data source after registering Back navigation.

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

        if (TvDeviceSessionStore.load(this) == null) {
            requestDevicePairing()
        } else {
            loadRealInspection()
        }
    }

    private var pairingRequested = false

    @Suppress("DEPRECATION")
    private fun requestDevicePairing() {
        if (pairingRequested) return

        pairingRequested = true
        startActivityForResult(
            Intent(this, TvPairingActivity::class.java),
            5601
        )
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(
        requestCode: Int,
        resultCode: Int,
        data: Intent?
    ) {
        super.onActivityResult(
            requestCode, resultCode, data
        )

        if (requestCode != 5601) return

        pairingRequested = false

        if (
            resultCode != RESULT_OK ||
            TvDeviceSessionStore.load(this) == null
        ) {
            finish()
            return
        }

        // Continue using the inspection-scoped HTTPS session.
        loadRealInspection()
    }

    override fun onResume() {
        super.onResume()

        val focusKey = evidenceReturnFocusKey ?: return
        evidenceReturnFocusKey = null

        val action = root.findViewWithTag<TextView>(focusKey)
            ?: return

        action.post {
            if (
                !isFinishing &&
                !isDestroyed &&
                action.isAttachedToWindow
            ) {
                action.requestFocus()
            }
        }
    }

    override fun onDestroy() {
        loadGeneration += 1
        bedrockGeneration += 1
        clearEvidence()

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

    private fun loadRealInspection() {
        if (isLoading) return

        isLoading = true
        loadError = null

        val generation = ++loadGeneration

        render()

        Thread({
            val result = runCatching {
                TvApiClient.load(applicationContext)
            }

            runOnUiThread {
                if (
                    isFinishing ||
                    isDestroyed ||
                    generation != loadGeneration
                ) {
                    return@runOnUiThread
                }

                isLoading = false

                result.onSuccess { loaded ->
                    clearEvidence()
                    bedrockGeneration += 1
                    bedrockBriefing = null
                    bedrockLoading = false
                    bedrockUnavailable = false
                    bedrockStatusMessage = null
                    inspection = loaded
                    currentPage = Page(Screen.INSPECTIONS)
                    history.clear()
                    loadError = null
                }.onFailure { failure ->
                    Log.e(
                        "RentReadyTV",
                        "Load failed: ${failure.javaClass.simpleName}"
                    )
                    loadError = if (
                        failure is SecurityException
                    ) {
                        "TV session expired or revoked. Pair this TV again."
                    } else {
                        "Could not load the inspection over HTTPS. " +
                            "Check the connection and retry."
                    }

                    if (failure is SecurityException) {
                        requestDevicePairing()
                    }
                }

                render()
            }
        }, "rentready-tv-https-loader").start()
    }

    private fun clearEvidence() {
        evidenceGeneration += 1
        evidenceBitmap = null
        evidenceFindingId = null
        evidenceLoading = false
        evidenceFailed = false
    }

    private fun loadEvidenceForFinding(findingId: String) {
        if (evidenceFindingId == findingId) {
            return
        }

        clearEvidence()

        val inspectionId = inspection.propertyId
        evidenceFindingId = findingId
        evidenceLoading = true

        val generation = evidenceGeneration

        Thread({
            val result = runCatching {
                TvApiClient.loadEvidenceImage(
                    applicationContext,
                    inspectionId,
                    findingId
                )
            }

            runOnUiThread {
                // Never display a response for an older screen,
                // inspection, or completed Activity instance.
                if (
                    isFinishing ||
                    isDestroyed ||
                    generation != evidenceGeneration ||
                    evidenceFindingId != findingId ||
                    currentPage.screen != Screen.FINDING ||
                    currentPage.findingId != findingId ||
                    inspection.propertyId != inspectionId
                ) {
                    return@runOnUiThread
                }

                evidenceLoading = false

                result.onSuccess { bitmap ->
                    evidenceBitmap = bitmap
                    evidenceFailed = false
                    Log.i(
                        "RentReadyTV",
                        "Real preserved evidence image loaded"
                    )
                }.onFailure { failure ->
                    evidenceBitmap = null
                    evidenceFailed = true

                    // Never log image URLs or private storage keys.
                    Log.w(
                        "RentReadyTV",
                        "Evidence load failed: " +
                            failure.javaClass.simpleName
                    )
                }

                render()
            }
        }, "rentready-tv-evidence-loader").start()
    }


    private fun loadBedrockIfNeeded(force: Boolean = false) {
        if (
            bedrockLoading ||
            bedrockBriefing != null ||
            (bedrockUnavailable && !force)
        ) {
            return
        }

        val inspectionId = inspection.propertyId
        val generation = ++bedrockGeneration

        bedrockLoading = true
        bedrockStatusMessage = null

        Thread({
            val result = runCatching {
                TvApiClient.loadCachedBedrockBriefing(
                    applicationContext, inspection
                )
            }

            runOnUiThread {
                if (
                    isFinishing ||
                    isDestroyed ||
                    generation != bedrockGeneration ||
                    inspection.propertyId != inspectionId ||
                    currentPage.screen != Screen.BRIEFING
                ) {
                    return@runOnUiThread
                }

                bedrockLoading = false

                result.onSuccess { briefing ->
                    bedrockBriefing = briefing
                    bedrockUnavailable = briefing == null
                    bedrockStatusMessage = if (briefing == null) {
                        "No saved Bedrock briefing is available. " +
                            "Showing the inspection summary."
                    } else {
                        null
                    }
                }.onFailure { failure ->
                    bedrockBriefing = null
                    bedrockUnavailable = true
                    bedrockStatusMessage = if (
                        failure is SecurityException
                    ) {
                        "TV authorization expired. Pair again."
                    } else {
                        "Network or briefing service unavailable. " +
                            "Showing the saved inspection summary."
                    }

                    Log.w(
                        "RentReadyTV",
                        "Cached briefing load failed: " +
                            failure.javaClass.simpleName
                    )

                    if (failure is SecurityException) {
                        requestDevicePairing()
                    }
                }

                render()
            }
        }, "rentready-tv-bedrock-cache").start()
    }

    private fun navigateTo(page: Page) {
        // Invalidate an in-flight briefing response when leaving.
        if (
            currentPage.screen == Screen.BRIEFING &&
                page.screen != Screen.BRIEFING
        ) {
            bedrockGeneration += 1
            bedrockLoading = false
        }
        if (
            page.screen != Screen.FINDING ||
            page.findingId != currentPage.findingId
        ) {
            clearEvidence()
        }

        val focusedKey =
            (root.findFocus() as? TextView)?.tag as? String

        history.add(
            currentPage.copy(focusKey = focusedKey)
        )
        currentPage = page
        render()
    }

    private fun navigateBack() {
        // Back must also release an abandoned loading state.
        if (currentPage.screen == Screen.BRIEFING) {
            bedrockGeneration += 1
            bedrockLoading = false
        }

        clearEvidence()

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
        focusKey: String = label,
        action: () -> Unit
    ): TextView {
        val view = TextView(this).apply {
            text = label
            tag = focusKey
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
        if (currentPage.screen == Screen.FINDING) {
            val findingId = currentPage.findingId
            val focusedKey =
                (root.findFocus() as? TextView)?.tag as? String

            if (
                findingId != null &&
                focusedKey in setOf(
                    "view:$findingId",
                    "play:$findingId",
                    "back:$findingId"
                )
            ) {
                currentPage = currentPage.copy(
                    focusKey = focusedKey
                )
            }
        }

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

        // Never substitute offline demo data after HTTPS errors.
        if (
            isLoading ||
            loadError != null ||
            !::inspection.isInitialized
        ) {
            addText(column, "RENTREADY VISION", 40f, 28, true)

            addText(
                column,
                if (isLoading) "LOADING REAL INSPECTION"
                else "CONNECTION UNAVAILABLE",
                27f,
                24,
                true
            )

            addText(
                column,
                if (isLoading)
                    "Connecting securely to RentReady Vision..."
                else
                    loadError ?: "The secure connection is unavailable.",
                21f,
                30
            )

            val action = addAction(
                column,
                if (isLoading) "EXIT" else "RETRY CONNECTION"
            ) {
                if (isLoading) {
                    finish()
                } else {
                    loadRealInspection()
                }
            }

            action.post { action.requestFocus() }
            return
        }

        val firstAction = when (currentPage.screen) {
            Screen.INSPECTIONS -> showInspections(column)
            Screen.OVERVIEW -> showOverview(column)
            Screen.ROOM -> showRoom(column)
            Screen.FINDING -> showFinding(column)
            Screen.BRIEFING -> showBriefing(column)
        }

        // Restore the previous selection when returning with Back.
        // Stable IDs avoid collisions between repeated finding titles.
        val target = currentPage.focusKey
            ?.let { root.findViewWithTag<TextView>(it) }
            ?: firstAction

        target.post {
            if (target.isAttachedToWindow) {
                target.requestFocus()
            }
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
            if (inspection.findings.isEmpty())
                "No findings reported"
            else
                "${inspection.findings.size} potential findings",
            27f,
            20,
            true
        )

        for (severity in listOf("HIGH", "MEDIUM", "LOW", "UNKNOWN")) {
            addText(
                column,
                "$severity       ${inspection.severityCount(severity)}",
                21f,
                9
            )
        }

        if (DemoReviewerAssessment.applies(inspection)) {
            addText(
                column,
                "HUMAN REVIEW: 5 CONFIRMED / 7 FALSE POSITIVES",
                21f, 12, true,
                Color.rgb(160, 195, 226)
            )
            addText(
                column,
                "Original AI detections are preserved. " +
                    "These classifications come from a separate review.",
                18f, 20, tint = Color.LTGRAY
            )
        }

        addText(column, "ROOMS", 27f, 18, true)

        var first: TextView? = null

        for (room in inspection.rooms) {
            val count = inspection.findingsInRoom(room.id).size
            val summary = if (count == 0) "No reported findings" else if (count == 1) "1 finding" else "$count findings"

            val action = addAction(
                column,
                "${room.name}     $summary",
                focusKey = "room:${room.id}"
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
            if (findings.isEmpty()) "NO REPORTED FINDINGS"
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
            val reviewerStatus =
                DemoReviewerAssessment.statusFor(inspection, finding)

            if (reviewerStatus != null) {
                addText(
                    column,
                    if (reviewerStatus == DemoReviewStatus.CONFIRMED)
                        "HUMAN REVIEW: CONFIRMED"
                    else
                        "HUMAN REVIEW: FALSE POSITIVE",
                    17f, 7, true,
                    Color.rgb(160, 195, 226)
                )
            }
            val action = addAction(
                column,
                "${finding.title}\n${finding.severity}",
                focusKey = "finding:${finding.id}"
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

        loadEvidenceForFinding(findingId)

        // A compact TV-first layout avoids unnecessary vertical
        // scrolling on ordinary finding-detail screens.
        column.setPadding(
            dp(40), dp(18), dp(40), dp(18)
        )

        addText(
            column,
            room.name.uppercase(),
            24f,
            6,
            true
        )

        addText(
            column,
            finding.title,
            30f,
            14,
            true
        )

        val reviewStatus =
            DemoReviewerAssessment.statusFor(inspection, finding)

        if (reviewStatus != null) {
            addText(
                column,
                if (reviewStatus == DemoReviewStatus.CONFIRMED)
                    "HUMAN REVIEW: CONFIRMED FINDING"
                else
                    "HUMAN REVIEW: FALSE POSITIVE - NOT CONFIRMED",
                18f, 12, true,
                Color.rgb(160, 195, 226)
            )
        }

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.TOP
        }

        val evidenceBox = FrameLayout(this).apply {
            background = GradientDrawable().apply {
                setColor(Color.rgb(30, 44, 65))
                cornerRadius = dp(12).toFloat()
                setStroke(
                    dp(1),
                    Color.rgb(85, 105, 135)
                )
            }

            val image = if (evidenceFindingId == findingId) {
                evidenceBitmap
            } else {
                null
            }

            if (image != null) {
                addView(
                    ImageView(this@MainActivity).apply {
                        setImageBitmap(image)
                        scaleType = ImageView.ScaleType.FIT_CENTER
                        contentDescription =
                            "Preserved inspection evidence image"
                    },
                    FrameLayout.LayoutParams(
                        FrameLayout.LayoutParams.MATCH_PARENT,
                        FrameLayout.LayoutParams.MATCH_PARENT
                    )
                )
            } else {
                val message = when {
                    evidenceLoading ->
                        "LOADING REAL EVIDENCE IMAGE..."

                    evidenceFailed ->
                        "EVIDENCE UNAVAILABLE - SELECT RETRY"

                    else ->
                        "EVIDENCE IMAGE UNAVAILABLE"
                }

                addView(
                    TextView(this@MainActivity).apply {
                        text = message
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
        }

        content.addView(
            evidenceBox,
            LinearLayout.LayoutParams(
                0,
                dp(340),
                1.25f
            ).apply {
                rightMargin = dp(24)
            }
        )

        val details = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }

        addText(
            details,
            "Severity    ${finding.severity}",
            22f,
            14
        )

        val confidenceLabel =
            finding.confidencePercent()?.let { "$it%" }
                ?: "Not available"

        addText(
            details,
            "Confidence    $confidenceLabel",
            22f,
            14
        )

        val timestampLabel = finding.timestampLabel()

        addText(
            details,
            if (timestampLabel == "Not available")
                "Evidence time unavailable"
            else
                "Detected at $timestampLabel",
            20f,
            16
        )

        addText(
            details,
            finding.description,
            21f,
            20
        )

        // Every saved demo finding may request its own
        // preserved image using the existing secure endpoint.
        val viewEvidence = addAction(
            details,
            "VIEW EVIDENCE",
            focusKey = "view:${finding.id}"
        ) {
            evidenceReturnFocusKey = "view:${finding.id}"

            // Pass finding identity only. Never send a signed
            // image URL, private S3 key or device token.
            startActivity(
                Intent(
                    this,
                    EvidenceImageActivity::class.java
                ).apply {
                    putExtra(
                        EvidenceImageActivity.EXTRA_INSPECTION_ID,
                        inspection.propertyId
                    )
                    putExtra(
                        EvidenceImageActivity.EXTRA_FINDING_ID,
                        finding.id
                    )
                    putExtra(
                        EvidenceImageActivity.EXTRA_TITLE,
                        finding.title.take(120)
                    )
                }
            )
        }

        // Prevent focus from escaping above the first action.
        viewEvidence.setOnKeyListener { _, keyCode, _ ->
            keyCode ==
                android.view.KeyEvent.KEYCODE_DPAD_UP
        }

        if (
            evidenceFailed &&
            evidenceFindingId == findingId &&
            !evidenceLoading
        ) {
            addAction(
                details,
                "RETRY EVIDENCE IMAGE",
                focusKey = "retry-evidence:$findingId"
            ) {
                // A retry starts one new authorized image fetch.
                // Never persist or display signed S3 URLs.
                clearEvidence()
                currentPage = currentPage.copy(
                    focusKey = "view:$findingId"
                )
                loadEvidenceForFinding(findingId)
                render()
            }
        }

        // Only three visually verified demo findings have
        // approved, inspection-scoped video evidence.
        val videoAvailable = (
            inspection.propertyId == videoInspectionId &&
                finding.id in videoFindingIds
        )

        if (videoAvailable) {
            addAction(
                details,
                "PLAY VIDEO EVIDENCE",
                focusKey = "play:${finding.id}"
            ) {
                evidenceReturnFocusKey = "play:${finding.id}"

                // The Intent contains no signed URL or token.
                // PlaybackActivity obtains its own fresh grant.
                startActivity(
                    Intent(
                        this,
                        PlaybackActivity::class.java
                    ).apply {
                        putExtra(
                            PlaybackActivity.EXTRA_INSPECTION_ID,
                            inspection.propertyId
                        )
                        putExtra(
                            PlaybackActivity.EXTRA_FINDING_ID,
                            finding.id
                        )
                        putExtra(
                            PlaybackActivity.EXTRA_TITLE,
                            finding.title.take(120)
                        )
                    }
                )
            }
        }

        val backToRoom = addAction(
            details,
            "BACK TO ROOM",
            focusKey = "back:${finding.id}"
        ) {
            navigateBack()
        }

        // Back is the final control. Up can move to Play,
        // or directly to View when no video is available.
        backToRoom.setOnKeyListener { _, keyCode, _ ->
            keyCode ==
                android.view.KeyEvent.KEYCODE_DPAD_DOWN
        }

        content.addView(
            details,
            LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f
            )
        )

        column.addView(
            content,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        )

        return backToRoom
    }


    private fun showReviewedDemoBriefing(
        column: LinearLayout
    ): TextView {
        loadBedrockIfNeeded()

        addText(
            column,
            "RENTAL READINESS BRIEFING",
            35f, 12, true
        )

        addText(
            column,
            "HUMAN REVIEW - NOT MODEL OUTPUT",
            19f, 16, true,
            Color.rgb(160, 195, 226)
        )

        addText(
            column,
            "12 original AI findings: 5 reviewer-confirmed " +
                "and 7 marked false positive.",
            24f, 18, true
        )

        addText(
            column,
            "Four Garage findings and one Bedroom 2 finding " +
                "were confirmed during human review. " +
                "The original inspection remains unchanged.",
            19f, 22, tint = Color.LTGRAY
        )

        addText(
            column,
            "REVIEWER-CONFIRMED EVIDENCE",
            25f, 16, true
        )

        var firstAction: TextView? = null

        for (finding in DemoReviewerAssessment.featured(inspection)) {
            val room = inspection.findRoom(finding.roomId)

            addText(
                column,
                room.name.uppercase() + " - " + finding.title,
                21f, 12, true
            )

            val action = addAction(
                column,
                "VIEW CONFIRMED FINDING AND EVIDENCE",
                focusKey = "review:${finding.id}"
            ) {
                navigateTo(
                    Page(
                        Screen.FINDING,
                        roomId = finding.roomId,
                        findingId = finding.id
                    )
                )
            }

            if (firstAction == null) firstAction = action
        }

        addText(
            column,
            "All original findings, including the other " +
                "confirmed Garage findings, remain available " +
                "through the property rooms.",
            17f, 22, tint = Color.LTGRAY
        )

        val ai = bedrockBriefing

        if (ai == null) {
            addText(
                column,
                if (bedrockLoading)
                    "Checking for the saved Bedrock briefing..."
                else
                    "BRIEFING UNAVAILABLE",
                21f, 12, true
            )

            if (!bedrockLoading) {
                addText(
                    column,
                    bedrockStatusMessage ?:
                        "The original AI response is not available.",
                    18f, 12, tint = Color.LTGRAY
                )

                addAction(
                    column,
                    "RETRY BRIEFING",
                    focusKey = "bedrock:retry"
                ) {
                    loadBedrockIfNeeded(force = true)
                    render()
                }
            }

            return requireNotNull(firstAction)
        }

        addText(
            column,
            "AMAZON BEDROCK - ORIGINAL PRE-REVIEW OUTPUT",
            20f, 14, true,
            Color.rgb(129, 190, 245)
        )

        addText(
            column,
            "The saved Bedrock response was generated before " +
                "human review. Two of its three priorities were " +
                "subsequently marked false positive.",
            19f, 16, tint = Color.LTGRAY
        )

        addText(
            column,
            "ORIGINAL AI HEADLINE - NOT REVIEWER-ENDORSED",
            16f, 6, true
        )

        addText(column, ai.headline, 22f, 20)

        for ((index, item) in ai.priorities.withIndex()) {
            val finding = inspection.findFinding(item.findingId)
            val room = inspection.findRoom(finding.roomId)

            val confirmed =
                DemoReviewerAssessment.statusFor(
                    inspection, finding
                ) == DemoReviewStatus.CONFIRMED

            addText(
                column,
                "BEDROCK PRIORITY ${index + 1}: " +
                    room.name.uppercase(),
                20f, 8, true
            )

            addText(
                column,
                if (confirmed)
                    "HUMAN REVIEW: CONFIRMED"
                else
                    "HUMAN REVIEW: FALSE POSITIVE - REJECTED",
                19f, 9, true,
                Color.rgb(160, 195, 226)
            )

            addText(column, finding.title, 21f, 8, true)
            addText(column, item.reason, 18f, 10)

            addText(
                column,
                if (confirmed)
                    "ORIGINAL AI SUGGESTION - REQUIRES REVIEW"
                else
                    "ORIGINAL AI SUGGESTION - NOT ENDORSED",
                16f, 6, true
            )

            addText(
                column, item.recommendedAction,
                18f, 12
            )

            addAction(
                column,
                "VIEW ORIGINAL FINDING AND EVIDENCE",
                focusKey = "bedrock:${finding.id}"
            ) {
                navigateTo(
                    Page(
                        Screen.FINDING,
                        roomId = finding.roomId,
                        findingId = finding.id
                    )
                )
            }
        }

        addText(
            column,
            ai.disclaimer,
            17f, 12, tint = Color.LTGRAY
        )

        return requireNotNull(firstAction)
    }

    private fun showBriefing(column: LinearLayout): TextView {
        if (DemoReviewerAssessment.applies(inspection)) {
            return showReviewedDemoBriefing(column)
        }

        if (inspection.findings.isEmpty()) {
            addText(
                column,
                "RENTAL READINESS BRIEFING",
                35f, 24, true
            )

            addText(
                column,
                "NO FINDINGS REPORTED",
                29f, 20, true
            )

            addText(
                column,
                "The saved inspection analysis did not report " +
                    "potential issues. This does not certify that " +
                    "the property is clear. Human review is still " +
                    "recommended.",
                22f, 24
            )

            addText(
                column,
                inspection.briefing.secondaryMessage,
                19f, 26,
                tint = Color.LTGRAY
            )

            // No Bedrock request is made for an empty report.
            return addAction(column, "BACK TO PROPERTY") {
                navigateBack()
            }
        }

        loadBedrockIfNeeded()

        val ai = bedrockBriefing

        if (ai != null) {
            addText(
                column,
                "RENTAL READINESS BRIEFING",
                35f, 12, true
            )

            addText(
                column,
                "GENERATED WITH AMAZON BEDROCK",
                19f, 25, true,
                Color.rgb(129, 190, 245)
            )

            addText(column, ai.headline, 29f, 27, true)

            var firstAction: TextView? = null

            for ((index, item) in ai.priorities.withIndex()) {
                val finding = inspection.findFinding(
                    item.findingId
                )

                val room = inspection.findRoom(finding.roomId)

                addText(
                    column,
                    "${index + 1}. ${room.name.uppercase()}  |  " +
                        finding.severity,
                    19f, 9, true,
                    Color.rgb(160, 195, 226)
                )

                addText(
                    column, finding.title, 25f, 15, true
                )

                addText(
                    column, "WHY REVIEW THIS FINDING",
                    16f, 5, true, Color.LTGRAY
                )

                addText(column, item.reason, 20f, 14)

                addText(
                    column, "SUGGESTED NEXT STEP",
                    16f, 5, true, Color.LTGRAY
                )

                addText(
                    column, item.recommendedAction,
                    20f, 16
                )

                val action = addAction(
                    column,
                    "VIEW SAVED FINDING AND EVIDENCE",
                    focusKey = "bedrock:${finding.id}"
                ) {
                    navigateTo(
                        Page(
                            Screen.FINDING,
                            roomId = finding.roomId,
                            findingId = finding.id
                        )
                    )
                }

                if (firstAction == null) {
                    firstAction = action
                }
            }

            addText(
                column, ai.disclaimer,
                17f, 12, tint = Color.LTGRAY
            )

            return requireNotNull(firstAction)
        }

        // Keep the previously working deterministic
        // briefing when the Bedrock cache is unavailable.
        val briefing = inspection.briefing
        val room = inspection.findRoom(
            briefing.priorityRoomId
        )

        addText(
            column,
            briefing.title.uppercase(),
            35f, 20, true
        )

        if (bedrockLoading) {
            addText(
                column,
                "Checking for a saved Bedrock briefing...",
                19f, 16, tint = Color.LTGRAY
            )
        } else if (bedrockUnavailable) {
            addText(
                column,
                "BRIEFING UNAVAILABLE",
                22f, 8, true
            )
            addText(
                column,
                bedrockStatusMessage ?:
                    "Showing the saved inspection summary.",
                19f, 16, tint = Color.LTGRAY
            )
        } else {
            addText(
                column,
                "SAVED INSPECTION SUMMARY",
                19f, 16, tint = Color.LTGRAY
            )
        }

        addText(
            column, briefing.headline,
            28f, 30, true
        )

        addText(
            column, room.name, 25f, 12, true
        )

        addText(
            column, briefing.priorityAction,
            22f, 30
        )

        addText(
            column,
            briefing.secondaryMessage,
            22f, 26
        )

        val firstAction = addAction(
            column, "VIEW PRIORITY FINDINGS"
        ) {
            navigateTo(
                Page(
                    Screen.ROOM,
                    roomId = briefing.priorityRoomId
                )
            )
        }

        if (!bedrockLoading) {
            addAction(
                column,
                "RETRY BRIEFING",
                focusKey = "bedrock:retry"
            ) {
                loadBedrockIfNeeded(force = true)
                render()
            }
        }

        return firstAction
    }

}
