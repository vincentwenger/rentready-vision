"""Real Chromium test for Step 52 batched report frame URLs."""

import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGE_URL = "http://rentready.test/"
BATCH_PATH = "/inspections/local-test/frames/urls"

IMAGE_DATA = (
    "data:image/gif;base64,"
    "R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


def test_120_frames_render_with_one_batch_request(browser):
    context = browser.new_context()
    page = context.new_page()
    requests = []
    errors = []

    page.on("pageerror", lambda error: errors.append(str(error)))

    html = (ROOT / "web" / "index.html").read_text(
        encoding="utf-8"
    )

    def serve(route):
        url = route.request.url

        if url == PAGE_URL:
            route.fulfill(
                status=200,
                content_type="text/html",
                body=html,
            )
            return

        if url.endswith(BATCH_PATH):
            requests.append(BATCH_PATH)

            result = {
                "inspection_id": "local-test",
                "frames": [
                    {
                        "index": index,
                        "url": IMAGE_DATA + f"#frame-{index}",
                        "expires_in_seconds": 900,
                    }
                    for index in range(120)
                ],
            }

            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(result),
            )
            return

        if "/inspections/" in url:
            requests.append(url)

        # Never allow the test browser to contact external services.
        route.abort()

    page.route("**/*", serve)

    try:
        page.goto(PAGE_URL, wait_until="load")

        page.evaluate("""
          async () => {
            const keyframes = Array.from(
              {length: 120},
              (_, index) => ({
                index,
                timestamp_seconds: index * 10,
                scene_index: 0,
                evidence_quality_score: 85,
                selection_reason: "adaptive",
                sharpness: 100,
                brightness: 100,
                motion_percent_per_second: 0,
                keyframe_selection_score: null,
                tile_median_sharpness: null
              })
            );

            await renderResults("local-test", {
              video: {
                duration_seconds: 2432.82,
                total_frames: 72989
              },
              processing: {
                sampled_frames: 2433,
                rejected_blur: 0,
                rejected_duplicate: 0,
                selected_keyframes: 120,
                opencv_operations: [],
                runtime: {}
              },
              keyframes,
              scenes: []
            });
          }
        """)

        assert requests == [BATCH_PATH]
        assert page.locator("#frames figure").count() == 120
        assert page.locator("#frames img").count() == 120

        assert page.locator(
            "#frames img"
        ).first.get_attribute("src").endswith("#frame-0")

        assert page.locator(
            "#frames img"
        ).last.get_attribute("src").endswith("#frame-119")

        assert not page.locator("#results").is_hidden()
        assert errors == []

    finally:
        context.close()
