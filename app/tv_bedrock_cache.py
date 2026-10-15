"""One-generation-per-fingerprint briefing cache.

The caller must authenticate and authorize the inspection.
No AWS calls occur on import.
"""

import hashlib
import json
from botocore.exceptions import ClientError

from .tv_bedrock_briefing import (
    MODEL_ID,
    SYSTEM_PROMPT,
    BriefingRejected,
    generate_briefing,
    prepare_findings,
)

class BriefingPending(RuntimeError):
    pass


def fingerprint(projection):
    payload = {
        "inspection_id": projection.overview.id,
        "model_id": MODEL_ID,
        "system_prompt_sha256": hashlib.sha256(
            SYSTEM_PROMPT.encode("utf-8")
        ).hexdigest(),
        "findings": prepare_findings(projection),
    }

    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    )

    return hashlib.sha256(text.encode()).hexdigest()


def _key(projection):
    return {
        "PK": "TV_BRIEFING#" + projection.overview.id,
        "SK": "SOURCE#" + fingerprint(projection),
    }


def _validate_payload(projection, payload):
    if not isinstance(payload, dict):
        raise BriefingRejected("Invalid cached briefing")

    if set(payload) != {
        "inspection_id", "source", "model_id",
        "input_sha256", "headline",
        "priority_findings", "disclaimer", "usage",
    }:
        raise BriefingRejected("Unexpected cached fields")

    if (
        payload["inspection_id"] != projection.overview.id
        or payload["source"] != "amazon-bedrock"
        or payload["model_id"] != MODEL_ID
    ):
        raise BriefingRejected("Cached briefing identity mismatch")

    if (
        not isinstance(payload["headline"], str)
        or not 1 <= len(payload["headline"].strip()) <= 150
    ):
        raise BriefingRejected("Invalid cached headline")

    approved = {
        item["finding_id"]: item
        for item in prepare_findings(projection)
    }

    priorities = payload["priority_findings"]

    if not isinstance(priorities, list) or not 1 <= len(priorities) <= 3:
        raise BriefingRejected("Invalid cached priorities")

    seen = set()

    for item in priorities:
        if not isinstance(item, dict) or set(item) != {
            "finding_id", "room", "severity",
            "title", "timestamp_seconds",
            "reason", "recommended_action",
        }:
            raise BriefingRejected("Invalid priority structure")

        finding_id = item["finding_id"]

        if finding_id not in approved or finding_id in seen:
            raise BriefingRejected("Unknown or duplicate finding")

        seen.add(finding_id)
        original = approved[finding_id]

        for field in (
            "room", "severity", "title",
            "timestamp_seconds",
        ):
            if item[field] != original[field]:
                raise BriefingRejected(
                    "Priority source fields changed"
                )

        for field, limit in (
            ("reason", 240),
            ("recommended_action", 280),
        ):
            value = item[field]
            if (
                not isinstance(value, str)
                or not 1 <= len(value.strip()) <= limit
            ):
                raise BriefingRejected("Invalid priority advice")

    if (
        not isinstance(payload["disclaimer"], str)
        or "human review" not in payload["disclaimer"].lower()
    ):
        raise BriefingRejected("Human-review disclaimer missing")

    return payload


def get_cached(projection, table):
    key = _key(projection)

    response = table.get_item(
        Key=key, ConsistentRead=True
    )

    item = response.get("Item")

    if item is None:
        return None

    if item.get("status") != "COMPLETE":
        raise BriefingPending(
            "Briefing generation requires operator review"
        )

    if item.get("fingerprint") != fingerprint(projection):
        raise BriefingRejected("Cache fingerprint mismatch")

    raw = item.get("payload_json")

    if not isinstance(raw, str) or len(raw) > 16000:
        raise BriefingRejected("Invalid cached payload")

    try:
        payload = json.loads(raw)
    except ValueError:
        raise BriefingRejected("Invalid cached JSON") from None

    return _validate_payload(projection, payload)


def generate_once(projection, table, client):
    """Operator-only caller; does not grant permissions itself."""
    existing = get_cached(projection, table)

    if existing is not None:
        return existing

    key = _key(projection)
    source_hash = fingerprint(projection)

    try:
        table.put_item(
            Item={
                **key,
                "entity_type": "tv_bedrock_briefing",
                "status": "GENERATING",
                "fingerprint": source_hash,
            },
            ConditionExpression=(
                "attribute_not_exists(PK) AND "
                "attribute_not_exists(SK)"
            ),
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get(
            "Code"
        ) == "ConditionalCheckFailedException":
            # Another request acquired the reservation.
            # Never make a duplicate inference call.
            cached = get_cached(projection, table)
            if cached is not None:
                return cached
            raise BriefingPending(
                "Generation already reserved"
            ) from None
        raise

    try:
        generated = generate_briefing(projection, client)
        validated = _validate_payload(projection, generated)

        serialized = json.dumps(
            validated, separators=(",", ":")
        )

        if len(serialized) > 16000:
            raise BriefingRejected("Generated briefing too large")

        table.update_item(
            Key=key,
            UpdateExpression=(
                "SET #s = :complete, payload_json = :payload"
            ),
            ConditionExpression="#s = :generating",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":complete": "COMPLETE",
                ":generating": "GENERATING",
                ":payload": serialized,
            },
        )

        return validated

    except Exception:
        # Fail closed: no automatic repeated paid generation.
        # Recovery of failed/stale reservations is an
        # explicit administrative action, not a TV action.
        try:
            table.update_item(
                Key=key,
                UpdateExpression="SET #s = :failed",
                ConditionExpression="#s = :generating",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":failed": "FAILED",
                    ":generating": "GENERATING",
                },
            )
        except Exception:
            pass
        raise
