"""Real Chromium cancellation tests with fully mocked network."""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


PAGE_URL = "http://rentready.test/"
INSPECTION_ID = "test-inspection"
ROOT = Path(__file__).resolve().parents[1]


MOCK_JS = r"""
(() => {
  const state = {
    calls: [],
    inspectionId: "test-inspection",
    holdCreation: false,
    releaseCreation: null,
    holdUpload: false,
    uploadStarted: false,
    uploadAborted: false,
    primaryStatus: "PROCESSING",
    agentStatus: "PROCESSING",
    holdAgentStart: false,
    releaseAgentStart: null,
    cancelFailures: 0,
    primaryCancelCalls: 0,
    agentCancelCalls: 0
  };

  window.__rrMock = state;

  const json = (data, status = 200) =>
    new Response(JSON.stringify(data), {
      status,
      headers: {"Content-Type": "application/json"}
    });

  window.fetch = (input, options = {}) => {
    const url = new URL(String(input), location.href);
    const path = url.pathname;
    const method = (options.method || "GET").toUpperCase();

    state.calls.push({method, path});

    if (url.hostname === "fake-s3.invalid") {
      state.uploadStarted = true;

      if (state.holdUpload) {
        return new Promise((resolve, reject) => {
          const abort = () => {
            state.uploadAborted = true;
            reject(new DOMException("Upload aborted", "AbortError"));
          };

          if (options.signal?.aborted) {
            abort();
          } else {
            options.signal?.addEventListener(
              "abort", abort, {once: true}
            );
          }
        });
      }

      return Promise.resolve(new Response("", {status: 200}));
    }

    if (path === "/inspections" && method === "POST") {
      if (state.holdCreation) {
        return new Promise(resolve => {
          state.releaseCreation = () => resolve(
            json({inspection_id: state.inspectionId})
          );
        });
      }

      return Promise.resolve(
        json({inspection_id: state.inspectionId})
      );
    }

    if (path.endsWith("/upload") && method === "POST") {
      return Promise.resolve(json({
        upload_url: "https://fake-s3.invalid/upload",
        required_headers: {"Content-Type": "video/mp4"}
      }));
    }

    if (path.endsWith("/upload-complete")) {
      return Promise.resolve(json({status: "UPLOADED"}));
    }

    if (path.endsWith("/process") && method === "POST") {
      return Promise.resolve(json({status: "QUEUED"}));
    }

    if (path.endsWith("/status") && method === "GET") {
      return Promise.resolve(json({
        inspection_id: state.inspectionId,
        status: state.primaryStatus,
        progress: null
      }));
    }

    if (path.endsWith("/agent/cancel") && method === "POST") {
      state.agentCancelCalls += 1;
      state.agentStatus = "CANCEL_REQUESTED";

      return Promise.resolve(json({
        status: "CANCEL_REQUESTED",
        primary_status: "COMPLETE",
        message: "Agent cancellation requested"
      }, 202));
    }

    if (path.endsWith("/cancel") && method === "POST") {
      state.primaryCancelCalls += 1;

      if (state.cancelFailures > 0) {
        state.cancelFailures -= 1;

        return Promise.resolve(json({
          detail: "Simulated cancellation service outage"
        }, 503));
      }

      state.primaryStatus = "CANCEL_REQUESTED";

      return Promise.resolve(json({
        status: "CANCEL_REQUESTED",
        message: "Primary cancellation requested"
      }, 202));
    }

    if (path.endsWith("/agent") && method === "GET") {
      return Promise.resolve(json({
        inspection_id: state.inspectionId,
        status: state.agentStatus,
        progress: null
      }));
    }

    if (path.endsWith("/frames") && method === "GET") {
      return Promise.resolve(json({
        keyframes: [],
        scenes: [],
        frame_assessments: []
      }));
    }

    if (path.endsWith("/issues/detect") && method === "POST") {
      return Promise.resolve(json({
        status: "COMPLETE",
        issues: []
      }));
    }

    if (path.endsWith("/agent/run") && method === "POST") {
      if (state.holdAgentStart) {
        return new Promise(resolve => {
          state.releaseAgentStart = () => {
            state.agentStatus = "PROCESSING";
            resolve(json({status: "QUEUED"}));
          };
        });
      }

      return Promise.resolve(json({status: "QUEUED"}));
    }

    // Fail closed: unexpected requests must not reach any server.
    return Promise.resolve(json({
      detail: "Unexpected mocked request: " + method + " " + path
    }, 404));
  };
})();
"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    current = context.new_page()
    current.set_default_timeout(8000)
    current.add_init_script(script=MOCK_JS)

    html = (ROOT / "web" / "index.html").read_text(
        encoding="utf-8"
    )

    def serve(route):
        if route.request.url == PAGE_URL:
            route.fulfill(
                status=200,
                content_type="text/html",
                body=html,
            )
        else:
            # No unmocked HTTP requests may leave Chromium.
            route.abort()

    current.route("**/*", serve)
    current.goto(PAGE_URL, wait_until="load")

    try:
        yield current
    finally:
        context.close()


def start_inspection(page):
    page.locator("#file").set_input_files({
        "name": "test-walkthrough.mp4",
        "mimeType": "video/mp4",
        "buffer": b"simulated-video-bytes",
    })

    page.locator("#run").click()


def wait_request(page, method, path):
    page.wait_for_function(
        """expected =>
          window.__rrMock.calls.some(
            call => call.method === expected.method &&
                    call.path === expected.path
          )""",
        arg={"method": method, "path": path},
    )


def requests(page):
    return page.evaluate("window.__rrMock.calls")


def test_cancel_during_inspection_creation(page):
    page.evaluate("window.__rrMock.holdCreation = true")

    start_inspection(page)

    wait_request(page, "POST", "/inspections")

    page.locator("#cancel-inspection").click()

    page.wait_for_function(
        "() => document.querySelector('#cancel-status').textContent.includes('Waiting')"
    )

    page.evaluate("window.__rrMock.releaseCreation()")

    wait_request(
        page, "POST",
        f"/inspections/{INSPECTION_ID}/cancel",
    )

    paths = [call["path"] for call in requests(page)]

    assert f"/inspections/{INSPECTION_ID}/upload" not in paths

    assert page.evaluate(
        "window.__rrMock.primaryCancelCalls"
    ) == 1


def test_cancel_aborts_active_s3_upload(page):
    page.evaluate("""
      window.__rrMock.holdUpload = true;
      window.__rrMock.primaryStatus = "UPLOAD_PENDING";
    """)

    start_inspection(page)

    page.wait_for_function(
        "() => window.__rrMock.uploadStarted"
    )

    page.locator("#cancel-inspection").click()

    page.wait_for_function(
        "() => window.__rrMock.uploadAborted"
    )

    wait_request(
        page, "POST",
        f"/inspections/{INSPECTION_ID}/cancel",
    )

    paths = [call["path"] for call in requests(page)]

    assert f"/inspections/{INSPECTION_ID}/upload-complete" not in paths
    assert f"/inspections/{INSPECTION_ID}/process" not in paths


def test_cancel_stops_primary_processing(page):
    start_inspection(page)

    wait_request(
        page, "GET",
        f"/inspections/{INSPECTION_ID}/status",
    )

    page.locator("#cancel-inspection").click()

    wait_request(
        page, "POST",
        f"/inspections/{INSPECTION_ID}/cancel",
    )

    page.wait_for_function(
        "() => window.__rrMock.primaryCancelCalls === 1"
    )

    paths = [call["path"] for call in requests(page)]

    assert f"/inspections/{INSPECTION_ID}/agent/run" not in paths
    assert f"/inspections/{INSPECTION_ID}/agent/enhance" not in paths


def test_cancel_routes_active_agent_to_agent_endpoint(page):
    page.evaluate("""
      window.__rrMock.primaryStatus = "COMPLETE";
      window.__rrMock.agentStatus = "PROCESSING";
    """)

    start_inspection(page)

    wait_request(
        page, "POST",
        f"/inspections/{INSPECTION_ID}/agent/run",
    )

    page.locator("#cancel-inspection").click()

    wait_request(
        page, "POST",
        f"/inspections/{INSPECTION_ID}/agent/cancel",
    )

    page.wait_for_function(
        "() => window.__rrMock.agentCancelCalls === 1"
    )

    paths = [call["path"] for call in requests(page)]

    assert f"/inspections/{INSPECTION_ID}/cancel" not in paths
    assert f"/inspections/{INSPECTION_ID}/agent/enhance" not in paths
    assert f"/inspections/{INSPECTION_ID}/agent/other-angle" not in paths
    assert f"/inspections/{INSPECTION_ID}/agent/policy" not in paths


def test_failed_cancellation_can_be_retried(page):
    page.evaluate("window.__rrMock.cancelFailures = 1")

    start_inspection(page)

    wait_request(
        page, "GET",
        f"/inspections/{INSPECTION_ID}/status",
    )

    page.locator("#cancel-inspection").click()

    page.wait_for_function(
        """() =>
          window.__rrMock.primaryCancelCalls === 1 &&
          document.querySelector('#cancel-inspection').textContent.trim()
            === 'Retry cancellation' &&
          !document.querySelector('#cancel-inspection').disabled"""
    )

    page.locator("#cancel-inspection").click()

    page.wait_for_function(
        "() => window.__rrMock.primaryCancelCalls === 2"
    )

    page.wait_for_function(
        """() => document.querySelector('#cancel-status')
          .textContent.includes('Cancellation requested')"""
    )

    assert page.evaluate(
        "window.__rrMock.primaryCancelCalls"
    ) == 2



def test_cancel_during_inflight_agent_launch(page):
    # The video is complete, but the new agent job has
    # not yet appeared in the server's status response.
    page.evaluate("""
      window.__rrMock.primaryStatus = "COMPLETE";
      window.__rrMock.agentStatus = "NOT_RUN";
      window.__rrMock.holdAgentStart = true;
    """)

    start_inspection(page)

    wait_request(
        page,
        "POST",
        f"/inspections/{INSPECTION_ID}/agent/run",
    )

    page.wait_for_function(
        "() => typeof window.__rrMock.releaseAgentStart === 'function'"
    )

    page.locator("#cancel-inspection").click()

    # The browser must not conclude that only the UI can stop
    # while an agent-job creation request is still outstanding.
    page.wait_for_function(
        """() => document.querySelector('#cancel-status')
          .textContent.includes('Waiting for the AI start request')"""
    )

    assert page.evaluate(
        "window.__rrMock.agentCancelCalls"
    ) == 0

    # The server now finishes registering the agent job.
    page.evaluate("window.__rrMock.releaseAgentStart()")

    wait_request(
        page,
        "POST",
        f"/inspections/{INSPECTION_ID}/agent/cancel",
    )

    page.wait_for_function(
        "() => window.__rrMock.agentCancelCalls === 1"
    )

    paths = [call["path"] for call in requests(page)]

    assert f"/inspections/{INSPECTION_ID}/cancel" not in paths

    assert (
        f"/inspections/{INSPECTION_ID}/agent/enhance"
        not in paths
    )
    assert (
        f"/inspections/{INSPECTION_ID}/agent/other-angle"
        not in paths
    )
    assert (
        f"/inspections/{INSPECTION_ID}/agent/policy"
        not in paths
    )

    assert "No active AI job was found" not in (
        page.locator("#cancel-status").inner_text()
    )



def test_agent_launch_timeout_offers_retry(page):
    page.evaluate("""
      window.__rrMock.primaryStatus = "COMPLETE";
      window.__rrMock.agentStatus = "NOT_RUN";
      window.__rrMock.holdAgentStart = true;
    """)

    start_inspection(page)

    wait_request(
        page,
        "POST",
        f"/inspections/{INSPECTION_ID}/agent/run",
    )

    page.locator("#cancel-inspection").click()

    page.wait_for_function(
        """() =>
          document.querySelector('#cancel-status')
            .textContent.includes(
              'Backend cancellation is not yet confirmed'
            ) &&
          document.querySelector('#cancel-inspection')
            .textContent.trim() === 'Retry cancellation' &&
          !document.querySelector('#cancel-inspection').disabled""",
        timeout=12000,
    )

    # The backend must not be reported as canceled when
    # the AI job-start request is still unresolved.
    assert page.evaluate(
        "window.__rrMock.agentCancelCalls"
    ) == 0

    status = page.locator("#cancel-status").inner_text()

    assert "not yet confirmed" in status
    assert "No active AI job was found" not in status


def test_late_agent_launch_triggers_automatic_cancellation(page):
    page.evaluate("""
      window.__rrMock.primaryStatus = "COMPLETE";
      window.__rrMock.agentStatus = "NOT_RUN";
      window.__rrMock.holdAgentStart = true;
    """)

    start_inspection(page)

    wait_request(
        page,
        "POST",
        f"/inspections/{INSPECTION_ID}/agent/run",
    )

    page.locator("#cancel-inspection").click()

    # Allow the initial cancellation request to time out.
    page.wait_for_function(
        """() =>
          document.querySelector('#cancel-inspection')
            .textContent.trim() === 'Retry cancellation' &&
          !document.querySelector('#cancel-inspection').disabled""",
        timeout=12000,
    )

    assert page.evaluate(
        "window.__rrMock.agentCancelCalls"
    ) == 0

    # The delayed server request now finishes registering the job.
    # Do not click Retry: the page should retry automatically.
    page.evaluate("window.__rrMock.releaseAgentStart()")

    page.wait_for_function(
        "() => window.__rrMock.agentCancelCalls === 1",
        timeout=8000,
    )

    page.wait_for_function(
        """() => document.querySelector('#cancel-status')
          .textContent.includes('Cancellation requested')"""
    )

    paths = [call["path"] for call in requests(page)]

    assert (
        f"/inspections/{INSPECTION_ID}/agent/cancel"
        in paths
    )

    assert (
        f"/inspections/{INSPECTION_ID}/agent/enhance"
        not in paths
    )

    assert (
        f"/inspections/{INSPECTION_ID}/agent/policy"
        not in paths
    )
