"""Scoped retention rules and safe merging with a bucket's existing rules."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from botocore.exceptions import ClientError

from .storage import VIDEO_TAG

PREFIXES = ("rentready/inspections/", "inspections/")
LEGACY_RULE_ID = "expire-prototype-video"


def lifecycle_rules(video_days: int = 30, noncurrent_days: int = 30, multipart_days: int = 7) -> list[dict]:
    if any(isinstance(days, bool) or not isinstance(days, int) or days < 1
           for days in (video_days, noncurrent_days, multipart_days)):
        raise ValueError("Retention days must be positive integers")
    rules = []
    for label, prefix in zip(("current", "legacy"), PREFIXES):
        rules.extend([
            {"ID": f"rentready-step39-{label}-videos", "Status": "Enabled",
             "Filter": {"And": {"Prefix": prefix, "Tags": [dict(VIDEO_TAG)]}},
             "Expiration": {"Days": video_days},
             "NoncurrentVersionExpiration": {"NoncurrentDays": noncurrent_days}},
            {"ID": f"rentready-step39-{label}-multipart", "Status": "Enabled",
             "Filter": {"Prefix": prefix},
             "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": multipart_days}},
            {"ID": f"rentready-step39-{label}-delete-markers", "Status": "Enabled",
             "Filter": {"Prefix": prefix},
             "Expiration": {"ExpiredObjectDeleteMarker": True}},
        ])
    return rules


def read_lifecycle(client: Any, bucket: str) -> dict:
    try:
        response = client.get_bucket_lifecycle_configuration(Bucket=bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchLifecycleConfiguration":
            return {"Rules": []}
        raise
    result = {"Rules": response.get("Rules", [])}
    if "TransitionDefaultMinimumObjectSize" in response:
        result["TransitionDefaultMinimumObjectSize"] = response["TransitionDefaultMinimumObjectSize"]
    return result


def merge_lifecycle(existing: dict, **days: int) -> dict:
    new_rules = lifecycle_rules(**days)
    ids = {rule["ID"] for rule in new_rules}
    retained = []
    for original in existing.get("Rules", []):
        rule = deepcopy(original)
        if rule.get("ID") in ids:
            continue
        if rule.get("ID") == LEGACY_RULE_ID:
            rule["Status"] = "Disabled"
        retained.append(rule)
    if len(retained) + len(new_rules) > 1000:
        raise ValueError("Merged lifecycle exceeds S3's 1000-rule limit")
    return {**existing, "Rules": retained + new_rules}


def retention_conflicts(configuration: dict) -> list[str]:
    """Do not claim evidence is retained when an unrelated broad rule expires it."""
    conflicts = []
    for rule in configuration.get("Rules", []):
        if rule.get("Status") != "Enabled" or str(rule.get("ID", "")).startswith("rentready-step39-"):
            continue
        expiration = rule.get("Expiration", {})
        if not ("Days" in expiration or "Date" in expiration or "NoncurrentVersionExpiration" in rule):
            continue
        filters = rule.get("Filter", {})
        combined = filters.get("And", {})
        prefix = combined.get("Prefix", filters.get("Prefix", rule.get("Prefix", "")))
        # Even tag/size filtered rules may expire retained evidence. Require review
        # unless the original-video tag proves that their scope is video-only.
        tags = combined.get("Tags", []) + ([filters["Tag"]] if "Tag" in filters else [])
        if VIDEO_TAG in tags:
            continue
        if any(root.startswith(prefix) or prefix.startswith(root) for root in PREFIXES):
            conflicts.append(str(rule.get("ID", "unnamed")))
    return conflicts


def write_lifecycle(client: Any, bucket: str, configuration: dict) -> None:
    conflicts = retention_conflicts(configuration)
    if conflicts:
        raise RuntimeError("Review overlapping expiration rules before applying Step 39: " + ", ".join(conflicts))
    args = {"Bucket": bucket, "LifecycleConfiguration": {"Rules": configuration["Rules"]}}
    if "TransitionDefaultMinimumObjectSize" in configuration:
        args["TransitionDefaultMinimumObjectSize"] = configuration["TransitionDefaultMinimumObjectSize"]
    client.put_bucket_lifecycle_configuration(**args)
