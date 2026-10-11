#!/usr/bin/env python3
"""Operator-only AWS CLI controls. No API token is read or written."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from uuid import uuid4

VERSION = "rentready-public-mode/1.0"
KEY = {"PK": {"S": "INSPECTION#PUBLIC_MODE_CONTROL"}, "SK": {"S": "SETTINGS"}}


def aws(action, request, args):
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as out:
            name = out.name
            json.dump(request, out)
        command = ["aws", "dynamodb", action, "--region", args.region, "--cli-input-json", "file://" + name,
                   "--output", "json", "--no-cli-pager"]
        if args.profile:
            command += ["--profile", args.profile]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            # AWS errors may contain request/context details; keep output bounded.
            raise RuntimeError("AWS control operation failed; check your AWS access, table, and concurrent changes")
        return json.loads(result.stdout or "{}")
    finally:
        if name:
            os.unlink(name)


def decode(item):
    return {name: value.get("S", int(value["N"]) if "N" in value else value.get("BOOL"))
            for name, value in item.items()}


def encode(value):
    if isinstance(value, bool): return {"BOOL": value}
    if isinstance(value, int): return {"N": str(value)}
    return {"S": str(value)}


def plan(old, args, now):
    if old and old.get("schema_version") != VERSION:
        raise RuntimeError("Unrecognized public-mode control schema")
    current_window = bool(old.get("window_id")) and int(old.get("expires_at_epoch", 0)) > now
    opening = args.enabled
    new_window = opening and not current_window
    if not old and not opening:
        raise RuntimeError("Public mode has no settings yet; enable it with all limits first")
    changes = {"revision": uuid4().hex, "updated_at_epoch": now}
    if opening:
        if args.hours is None and (new_window or not old):
            raise RuntimeError("Specify -Hours when starting a new judging window")
        if args.max_video_mb is None and not old:
            raise RuntimeError("Specify -MaxVideoMB for the first window")
        if args.max_inspections is None and not old:
            raise RuntimeError("Specify -MaxInspections for the first window")
        changes.update({"schema_version": VERSION, "enabled": True})
        if new_window:
            changes.update({"window_id": uuid4().hex, "admitted_count": 0})
        if args.hours is not None:
            changes["expires_at_epoch"] = now + int(args.hours * 3600)
    elif args.disabled:
        changes["enabled"] = False
    elif args.hours is not None:
        raise RuntimeError("-Hours requires -Enabled")
    if args.max_video_mb is not None:
        changes["max_upload_bytes"] = args.max_video_mb * 1_000_000
    if args.max_inspections is not None:
        used = 0 if new_window else int(old.get("admitted_count", 0))
        if args.max_inspections < used:
            raise RuntimeError("Quota cannot be smaller than the number already admitted")
        changes["max_inspections"] = args.max_inspections
    merged = {**old, **changes}
    if opening and not (0 < merged.get("max_upload_bytes", 0) <= 500_000_000 and merged.get("max_inspections", 0) > 0):
        raise RuntimeError("Valid upload and inspection limits are required")
    names = {"#revision": "revision", "#used": "admitted_count"}
    values = {}
    assignments = []
    for index, (name, value) in enumerate(changes.items()):
        names[f"#f{index}"] = name
        values[f":v{index}"] = encode(value)
        assignments.append(f"#f{index} = :v{index}")
    if old:
        condition = "#revision = :previous"
        values[":previous"] = encode(old["revision"])
    else:
        condition = "attribute_not_exists(PK)"
        names.pop("#revision")
    if not new_window and "max_inspections" in changes:
        condition += " AND #used <= :limit"
        values[":limit"] = encode(changes["max_inspections"])
    else:
        names.pop("#used")
    return {"TableName": args.table, "Key": KEY, "UpdateExpression": "SET " + ", ".join(assignments),
            "ConditionExpression": condition, "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values, "ReturnValues": "ALL_NEW"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--enabled", action="store_true")
    group.add_argument("--disabled", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--hours", type=float)
    parser.add_argument("--max-video-mb", type=int)
    parser.add_argument("--max-inspections", type=int)
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--table", default="rentready-vision-dev")
    parser.add_argument("--profile")
    parser.add_argument("--endpoint", default="https://rentreadyvision.com")
    args = parser.parse_args()
    if args.hours is not None and not 0 < args.hours <= 168: parser.error("Hours must be greater than 0 and at most 168")
    if args.max_video_mb is not None and not 1 <= args.max_video_mb <= 500: parser.error("MaxVideoMB must be 1..500")
    if args.max_inspections is not None and not 1 <= args.max_inspections <= 10000: parser.error("MaxInspections must be 1..10000")
    if args.status and (args.enabled or args.disabled or args.hours is not None or args.max_video_mb is not None or args.max_inspections is not None):
        parser.error("Status cannot be combined with changes")
    if not args.status and not (args.enabled or args.disabled or args.max_video_mb is not None or args.max_inspections is not None):
        parser.error("Choose an action")
    # Enabling is only permitted after this feature has been deployed.
    if args.enabled:
        if not args.endpoint.startswith("https://"): parser.error("An HTTPS endpoint is required")
        with urllib.request.urlopen(args.endpoint.rstrip("/") + "/public-mode", timeout=10) as response:
            supported = json.load(response)
        if supported.get("schema_version") != VERSION or supported.get("supported") is not True:
            raise RuntimeError("Public-mode support is not deployed; no settings were changed")
    old = decode(aws("get-item", {"TableName": args.table, "Key": KEY, "ConsistentRead": True}, args).get("Item", {}))
    if args.status:
        value = old
    else:
        request = plan(old, args, int(time.time()))
        value = decode(aws("update-item", request, args)["Attributes"])
    now = int(time.time())
    print(json.dumps({"enabled_setting": value.get("enabled", False),
                      "public_access_now": value.get("enabled") is True and int(value.get("expires_at_epoch", 0)) > now,
                      "expires_at_epoch": value.get("expires_at_epoch", 0),
                      "expires_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(value["expires_at_epoch"]))) if value.get("expires_at_epoch") else None,
                      "max_video_mb": int(value.get("max_upload_bytes", 0)) // 1_000_000,
                      "max_inspections": value.get("max_inspections", 0),
                      "admitted_inspections": value.get("admitted_count", 0),
                      "remaining_inspections": max(0, int(value.get("max_inspections", 0)) - int(value.get("admitted_count", 0)))}, indent=2))


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        raise SystemExit("Public-mode operation stopped: " + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)) from None
