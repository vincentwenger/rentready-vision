from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from botocore.exceptions import ClientError
from .aws import table


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ddb_safe(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_ddb_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _ddb_safe(v) for k, v in value.items()}
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def inspection_pk(inspection_id: str) -> str:
    return f"INSPECTION#{inspection_id}"


def create_inspection(inspection_id: str, *, purpose: str, property_label: str | None) -> dict[str, Any]:
    now = utc_now()
    item = {
        "PK": inspection_pk(inspection_id),
        "SK": "METADATA",
        "entity_type": "inspection",
        "inspection_id": inspection_id,
        "status": "CREATED",
        "purpose": purpose,
        "property_label": property_label,
        "created_at": now,
        "updated_at": now,
    }
    table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)")
    return item


def get_inspection(inspection_id: str) -> dict[str, Any] | None:
    result = table.get_item(Key={"PK": inspection_pk(inspection_id), "SK": "METADATA"}, ConsistentRead=True)
    item = result.get("Item")
    return _json_safe(item) if item else None


def update_inspection(inspection_id: str, **changes: Any) -> dict[str, Any]:
    changes["updated_at"] = utc_now()
    names: dict[str, str] = {}
    values: dict[str, Any] = {}
    parts: list[str] = []
    for idx, (key, value) in enumerate(changes.items()):
        name_key = f"#n{idx}"
        value_key = f":v{idx}"
        names[name_key] = key
        values[value_key] = _ddb_safe(value)
        parts.append(f"{name_key} = {value_key}")
    try:
        result = table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": "METADATA"},
            UpdateExpression="SET " + ", ".join(parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(PK) AND attribute_exists(SK)",
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise KeyError(inspection_id) from exc
        raise
    return _json_safe(result["Attributes"])
