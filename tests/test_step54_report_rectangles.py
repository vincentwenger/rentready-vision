"""Step 54: real Chromium validation of report bounding boxes."""

import base64
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGE_URL = "http://rentready.test/"
FRAME_URL = "/inspections/step54-test/frames/0/url"

svg = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'width="800" height="400">'
    '<rect width="800" height="400" fill="#dddddd"/>'
    '</svg>'
)
IMAGE_URL = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(svg.encode()).decode()
)

ISSUE = {
    "title": "Visible wall crack",
    "description": "Crack visible on the wall.",
    "severity": "Review recommended",
    "confidence": 0.9,
    "confidence_label": "High",
    "evidence_start_seconds": 3,
    "evidence_end_seconds": 3,
    "representative_timestamp_seconds": 3,
    "representative_frame_index": 0,
    "evidence_summary": "Visible in the evidence image.",
    "recommended_action": "Review the damaged area.",
    "bbox": {
        "x": 0.20,
        "y": 0.30,
        "width": 0.40,
        "height": 0.20,
    },
}

CHECK_POSITION = """
() => {
  const card = document.querySelector("#step54-test-card");
  const img = card.querySelector("img");
  const marker = card.querySelector(".report-evidence-bbox");

  if (!marker || !img.naturalWidth) return false;

  const ir = img.getBoundingClientRect();
  const mr = marker.getBoundingClientRect();

  const scale = Math.min(
    ir.width / img.naturalWidth,
    ir.height / img.naturalHeight
  );

  const w = img.naturalWidth * scale;
  const h = img.naturalHeight * scale;

  const offsetX = (ir.width - w) / 2;
  const offsetY = (ir.height - h) / 2;

  const x = ir.left + offsetX + 0.20 * w;
  const y = ir.top + offsetY + 0.30 * h;

  return (
    Math.abs(mr.left - x) < 2 &&
    Math.abs(mr.top - y) < 2 &&
    Math.abs(mr.width - 0.40 * w) < 2 &&
    Math.abs(mr.height - 0.20 * h) < 2
  );
}
"""


def test_report_rectangles_in_chromium():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1200, "height": 900}
        )
        page = context.new_page()
        errors = []

        page.on("pageerror", lambda error: errors.append(str(error)))

        def serve(route):
            url = route.request.url

            if url == PAGE_URL:
                route.fulfill(
                    status=200,
                    content_type="text/html",
                    body=html,
                )
            elif url.endswith(FRAME_URL):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"url": IMAGE_URL}),
                )
            else:
                route.abort()

        page.route("**/*", serve)

        try:
            page.goto(PAGE_URL, wait_until="load")

            page.evaluate(
                """async issue => {
                    const card = await renderReportIssue(
                        "step54-test", issue
                    );
                    card.id = "step54-test-card";
                    document.body.appendChild(card);
                    await card.querySelector("img").decode();
                }""",
                ISSUE,
            )

            page.wait_for_function(CHECK_POSITION)

            desktop_width = page.locator(
                "#step54-test-card img"
            ).evaluate("(img) => img.getBoundingClientRect().width")

            assert page.locator(
                "#step54-test-card .report-rectangle-note"
            ).inner_text() == (
                "Red rectangle: AI-estimated area. Verify visually."
            )

            print("Rectangle explanation label: PASS")
            print("Desktop rectangle: PASS")

            page.set_viewport_size({
                "width": 390,
                "height": 844,
            })

            page.wait_for_function(CHECK_POSITION)

            mobile_width = page.locator(
                "#step54-test-card img"
            ).evaluate("(img) => img.getBoundingClientRect().width")

            assert mobile_width < desktop_width
            print("Responsive rectangle: PASS")


            # Full-frame boxes do not identify a specific location.
            broad_bbox = dict(ISSUE)
            broad_bbox["bbox"] = {
                "x": 0.0,
                "y": 0.0,
                "width": 1.0,
                "height": 1.0,
            }

            page.evaluate(
                """async issue => {
                    const card = await renderReportIssue(
                        "step54-test", issue
                    );
                    card.id = "step54-broad-bbox";
                    document.body.appendChild(card);
                }""",
                broad_bbox,
            )

            assert page.locator(
                "#step54-broad-bbox img"
            ).count() == 1

            assert page.locator(
                "#step54-broad-bbox .report-evidence-bbox"
            ).count() == 0

            assert page.locator(
                "#step54-broad-bbox .report-rectangle-note"
            ).count() == 0

            print("Full-frame rectangle suppressed: PASS")

            no_bbox = dict(ISSUE)
            no_bbox["bbox"] = None

            page.evaluate(
                """async issue => {
                    const card = await renderReportIssue(
                        "step54-test", issue
                    );
                    card.id = "step54-no-bbox";
                    document.body.appendChild(card);
                }""",
                no_bbox,
            )

            assert page.locator(
                "#step54-no-bbox .report-evidence-bbox"
            ).count() == 0

            assert page.locator(
                "#step54-no-bbox .report-rectangle-note"
            ).count() == 0

            print("Missing bounding box: PASS")
            assert errors == []
            print("Browser JavaScript errors: NONE")
        finally:
            context.close()
            browser.close()
