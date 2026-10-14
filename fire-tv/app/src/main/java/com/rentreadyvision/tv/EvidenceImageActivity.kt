package com.rentreadyvision.tv

import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Matrix
import android.os.Bundle
import android.view.Gravity
import android.view.KeyEvent
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.FragmentActivity
import java.util.UUID
import kotlin.math.min

/**
 * Remote-controlled evidence photograph viewer.
 *
 * No signed URLs, bitmaps or credentials are passed in Intents.
 * The image is fetched via the existing authenticated, bounded
 * TV image endpoint. No image modifications are persisted.
 */
class EvidenceImageActivity : FragmentActivity() {

    companion object {
        const val EXTRA_INSPECTION_ID =
            "com.rentreadyvision.tv.IMAGE_INSPECTION_ID"
        const val EXTRA_FINDING_ID =
            "com.rentreadyvision.tv.IMAGE_FINDING_ID"
        const val EXTRA_TITLE =
            "com.rentreadyvision.tv.IMAGE_FINDING_TITLE"
    }

    private lateinit var imageView: ImageView
    private lateinit var zoomStatus: TextView

    private var evidenceBitmap: Bitmap? = null
    private var loadGeneration = 0
    private var zoomIndex = 0

    private var panMode = false
    private var panX = 0f
    private var panY = 0f

    private val zoomFactors = floatArrayOf(
        1f, 1.5f, 2f, 3f
    )

    private fun dp(value: Int): Int {
        return (
            value * resources.displayMetrics.density + 0.5f
        ).toInt()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val inspectionId = intent.getStringExtra(
            EXTRA_INSPECTION_ID
        )
        val findingId = intent.getStringExtra(
            EXTRA_FINDING_ID
        )
        val session = TvDeviceSessionStore.load(this)

        val validInspection = inspectionId != null &&
            runCatching {
                UUID.fromString(inspectionId).toString() ==
                    inspectionId
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

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(16, 28, 48))
            setPadding(dp(24), dp(14), dp(24), dp(14))
        }

        val title = intent.getStringExtra(EXTRA_TITLE)
            ?.take(120)
            ?: "Inspection evidence"

        val header = TextView(this).apply {
            text = "VIEW EVIDENCE - $title"
            textSize = 24f
            setTextColor(Color.WHITE)
            setPadding(0, 0, 0, dp(12))
        }

        root.addView(header)

        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.TOP
        }

        val screenHeightDp = (
            resources.displayMetrics.heightPixels /
                resources.displayMetrics.density
        ).toInt()

        val viewerHeight = (
            screenHeightDp - 115
        ).coerceIn(240, 620)

        val imagePanel = FrameLayout(this).apply {
            setBackgroundColor(Color.rgb(30, 44, 65))
            clipChildren = true
            clipToPadding = true
        }

        imageView = ImageView(this).apply {
            scaleType = ImageView.ScaleType.MATRIX
            contentDescription =
                "Full-screen preserved inspection evidence photograph"
        }

        imagePanel.addView(
            imageView,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )

        row.addView(
            imagePanel,
            LinearLayout.LayoutParams(
                0, dp(viewerHeight), 1f
            ).apply {
                rightMargin = dp(18)
            }
        )

        val controls = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }

        zoomStatus = TextView(this).apply {
            text = "Loading original evidence photograph..."
            textSize = 16f
            setTextColor(Color.LTGRAY)
            setPadding(
                dp(10), dp(4), dp(8), dp(12)
            )
        }

        controls.addView(zoomStatus)

        fun addControl(
            label: String,
            onClick: () -> Unit
        ): TextView {
            val button = TextView(this).apply {
                text = label
                textSize = 19f
                setTextColor(Color.WHITE)
                gravity = Gravity.CENTER_VERTICAL
                setPadding(
                    dp(16), dp(12), dp(16), dp(12)
                )
                minHeight = dp(54)
                isFocusable = true
                isFocusableInTouchMode = true
                isClickable = true

                setOnFocusChangeListener { view, focused ->
                    view.setBackgroundColor(
                        if (focused)
                            Color.rgb(38, 89, 148)
                        else
                            Color.rgb(34, 50, 72)
                    )
                }

                setBackgroundColor(Color.rgb(34, 50, 72))
                setOnClickListener { onClick() }
            }

            controls.addView(
                button,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply {
                    bottomMargin = dp(9)
                }
            )

            return button
        }

        val zoomIn = addControl("ZOOM IN  +") {
            if (
                evidenceBitmap != null &&
                zoomIndex < zoomFactors.lastIndex
            ) {
                zoomIndex += 1
                updateImageMatrix()
            }
        }

        addControl("ZOOM OUT  -") {
            if (evidenceBitmap != null && zoomIndex > 0) {
                zoomIndex -= 1
                updateImageMatrix()
            }
        }

        addControl("FIT IMAGE") {
            zoomIndex = 0
            panX = 0f
            panY = 0f
            panMode = false
            updateImageMatrix()
        }

        addControl("PAN IMAGE") {
            if (evidenceBitmap == null) {
                zoomStatus.text = "Image still loading"
            } else if (zoomIndex == 0) {
                zoomStatus.text = "Zoom in before panning"
            } else {
                panMode = true
                updateImageMatrix()
            }
        }

        addControl("BACK TO FINDING") {
            finish()
        }

        row.addView(
            controls,
            LinearLayout.LayoutParams(
                dp(250),
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        )

        root.addView(
            row,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        )

        setContentView(root)
        zoomIn.post { zoomIn.requestFocus() }

        val generation = ++loadGeneration
        val appContext = applicationContext

        // The image load is bounded and runs off the UI thread.
        Thread({
            val result = runCatching {
                TvApiClient.loadEvidenceImage(
                    appContext,
                    inspectionId,
                    findingId
                )
            }

            runOnUiThread {
                if (
                    generation != loadGeneration ||
                    isFinishing ||
                    isDestroyed
                ) {
                    return@runOnUiThread
                }

                result.onSuccess { bitmap ->
                    evidenceBitmap = bitmap
                    imageView.setImageBitmap(bitmap)
                    imageView.post {
                        if (
                            generation == loadGeneration &&
                            !isFinishing &&
                            !isDestroyed
                        ) {
                            updateImageMatrix()
                        }
                    }
                }.onFailure {
                    zoomStatus.text =
                        "Evidence image unavailable. Press Back."
                }
            }
        }, "rentready-tv-full-evidence").start()
    }

    private fun updateImageMatrix() {
        val bitmap = evidenceBitmap ?: return

        val width = imageView.width.toFloat()
        val height = imageView.height.toFloat()

        if (width <= 0f || height <= 0f) return

        val fitScale = min(
            width / bitmap.width.toFloat(),
            height / bitmap.height.toFloat()
        )

        val scale = fitScale * zoomFactors[zoomIndex]

        val scaledWidth = bitmap.width.toFloat() * scale
        val scaledHeight = bitmap.height.toFloat() * scale

        val maxPanX = (
            (scaledWidth - width).coerceAtLeast(0f) / 2f
        )
        val maxPanY = (
            (scaledHeight - height).coerceAtLeast(0f) / 2f
        )

        panX = panX.coerceIn(-maxPanX, maxPanX)
        panY = panY.coerceIn(-maxPanY, maxPanY)

        val offsetX = (width - scaledWidth) / 2f + panX
        val offsetY = (height - scaledHeight) / 2f + panY

        val matrix = Matrix().apply {
            setScale(scale, scale)
            postTranslate(offsetX, offsetY)
        }

        imageView.imageMatrix = matrix

        val percent = (
            zoomFactors[zoomIndex] * 100
        ).toInt()

        zoomStatus.text = if (panMode) {
            "Zoom $percent% - PAN MODE: arrows move image; " +
                "CENTER or BACK exits"
        } else {
            "Zoom $percent% - Original evidence"
        }
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (panMode) {
            val isArrow = event.keyCode in setOf(
                KeyEvent.KEYCODE_DPAD_UP,
                KeyEvent.KEYCODE_DPAD_DOWN,
                KeyEvent.KEYCODE_DPAD_LEFT,
                KeyEvent.KEYCODE_DPAD_RIGHT
            )

            if (isArrow) {
                if (event.action == KeyEvent.ACTION_DOWN) {
                    val step = dp(36).toFloat()

                    when (event.keyCode) {
                        KeyEvent.KEYCODE_DPAD_UP ->
                            panY -= step
                        KeyEvent.KEYCODE_DPAD_DOWN ->
                            panY += step
                        KeyEvent.KEYCODE_DPAD_LEFT ->
                            panX -= step
                        KeyEvent.KEYCODE_DPAD_RIGHT ->
                            panX += step
                    }

                    updateImageMatrix()
                }

                return true
            }

            if (
                event.keyCode == KeyEvent.KEYCODE_DPAD_CENTER ||
                event.keyCode == KeyEvent.KEYCODE_ENTER ||
                event.keyCode == KeyEvent.KEYCODE_BACK
            ) {
                if (event.action == KeyEvent.ACTION_UP) {
                    panMode = false
                    updateImageMatrix()
                }
                return true
            }
        }

        return super.dispatchKeyEvent(event)
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onBackPressed() {
        if (panMode) {
            panMode = false
            updateImageMatrix()
        } else {
            super.onBackPressed()
        }
    }

    override fun onDestroy() {
        loadGeneration += 1
        evidenceBitmap = null

        if (::imageView.isInitialized) {
            imageView.setImageDrawable(null)
        }

        super.onDestroy()
    }
}
