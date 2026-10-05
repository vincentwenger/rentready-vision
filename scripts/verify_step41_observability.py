"""Verify RentReady Vision Step 41 observability wiring.

Repository mode is offline/read-only. Optional --live mode reads CloudWatch Logs
and metric metadata only; it does not mutate AWS resources or manufacture events.
"""
from __future__ import annotations

import argparse
import json
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify_repository(root: Path = ROOT) -> dict[str, Any]:
    from app.telemetry import STEP41_METRICS, STEP41_REQUIRED_EVENTS

    telemetry = (root / "app" / "telemetry.py").read_text(encoding="utf-8")
    services = (root / "app" / "services.py").read_text(encoding="utf-8")
    routes = (root / "app" / "routers" / "inspections.py").read_text(encoding="utf-8")
    worker = (root / "scripts" / "cool_worker.py").read_text(encoding="utf-8")
    benchmark = (root / "scripts" / "run_cool_step8.py").read_text(encoding="utf-8")
    terraform = (root / "infra" / "terraform" / "main.tf").read_text(encoding="utf-8")

    combined = "\n".join((telemetry, services, routes, worker, benchmark))
    event_wiring = {event: f'"{event}"' in combined for event in sorted(STEP41_REQUIRED_EVENTS)}
    metric_wiring = {metric: f'"{metric}"' in telemetry for metric in sorted(STEP41_METRICS)}
    checks = {
        "all_required_events_wired": all(event_wiring.values()),
        "all_required_metrics_wired": all(metric_wiring.values()),
        "api_upload_event_wired": '"VIDEO_UPLOADED"' in routes,
        "ai_analysis_events_wired": all(name in services for name in (
            '"AI_ANALYSIS_STARTED"', '"CANDIDATES_FOUND"', '"REPORT_COMPLETE"'
        )),
        "video_events_wired": all(name in services for name in (
            '"OPENCV_STARTED"', '"SCENE_EXTRACTION_COMPLETE"', '"KEYFRAMES_SELECTED"',
            '"COOL_RUNTIME_VERIFIED"'
        )),
        "agent_events_wired": all(name in worker for name in (
            '"AGENT_TOOL_CALL"', '"AGENT_VERIFICATION_COMPLETE"'
        )),
        "benchmark_event_wired": '"COOL_BENCHMARK_COMPLETE"' in benchmark,
        "failure_event_wired": '"PROCESSING_FAILED"' in worker and '"PROCESSING_FAILED"' in services,
        "api_cloudwatch_log_permission": "WriteInspectionObservabilityLogs" in terraform,
        "api_cloudwatch_metric_permission": "PublishInspectionObservabilityMetrics" in terraform,
        "metric_namespace_scoped": '"cloudwatch:namespace" = "RentReadyVision/Processing"' in terraform,
        "low_cardinality_dimensions": all(token in telemetry for token in (
            '"Environment"', '"Operation"', '"Stage"'
        )),
    }
    return {
        "step": 41,
        "mode": "repository",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(checks.values()),
        "checks": checks,
        "required_events": sorted(STEP41_REQUIRED_EVENTS),
        "required_metrics": STEP41_METRICS,
        "event_wiring": event_wiring,
        "metric_wiring": metric_wiring,
        "live_aws_verified": False,
        "note": "Repository PASS proves instrumentation is wired; deploy and exercise upload, processing, AI, agent, and benchmark paths for a live CloudWatch pass.",
    }


def verify_live(*, lookback_hours: int = 168) -> dict[str, Any]:
    from app.aws import session
    from app.config import get_settings
    from app.telemetry import STEP41_METRICS, STEP41_REQUIRED_EVENTS

    settings = get_settings()
    logs = session.client("logs")
    cloudwatch = session.client("cloudwatch")
    start_ms = int((time.time() - max(1, lookback_hours) * 3600) * 1000)
    found_events: set[str] = set()
    next_token: str | None = None
    while True:
        request: dict[str, Any] = {
            "logGroupName": settings.cool_log_group,
            "startTime": start_ms,
            "filterPattern": '{ $.event = * }',
            "limit": 10000,
        }
        if next_token:
            request["nextToken"] = next_token

        response = logs.filter_log_events(**request)
        for item in response.get("events", []):
            try:
                payload = json.loads(item.get("message") or "{}")
            except json.JSONDecodeError:
                continue
            event = payload.get("event")
            if event in STEP41_REQUIRED_EVENTS:
                found_events.add(str(event))

        new_token = response.get("nextToken")
        if not new_token or new_token == next_token:
            break
        next_token = new_token

    metric_presence: dict[str, bool] = {}
    for metric in STEP41_METRICS:
        listed = cloudwatch.list_metrics(
            Namespace=settings.cloudwatch_metrics_namespace,
            MetricName=metric,
            RecentlyActive="PT3H" if lookback_hours <= 3 else None,
        ) if lookback_hours <= 3 else cloudwatch.list_metrics(
            Namespace=settings.cloudwatch_metrics_namespace,
            MetricName=metric,
        )
        metric_presence[metric] = bool(listed.get("Metrics"))

    missing_events = sorted(STEP41_REQUIRED_EVENTS - found_events)
    missing_metrics = sorted(name for name, present in metric_presence.items() if not present)
    passed = not missing_events and not missing_metrics
    return {
        "step": 41,
        "mode": "live_cloudwatch_read_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": lookback_hours,
        "log_group": settings.cool_log_group,
        "metrics_namespace": settings.cloudwatch_metrics_namespace,
        "passed": passed,
        "live_aws_verified": passed,
        "events_seen": sorted(found_events),
        "missing_events": missing_events,
        "metric_presence": metric_presence,
        "missing_metrics": missing_metrics,
        "note": "Missing events can simply mean that path was not exercised during the lookback window; this verifier never creates synthetic traffic.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Read CloudWatch and verify observed events/metrics")
    parser.add_argument("--lookback-hours", type=int, default=168)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_live(lookback_hours=args.lookback_hours) if args.live else verify_repository()
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
