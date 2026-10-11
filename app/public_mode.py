"""Temporary public judging window. Operator authentication remains authoritative.

A quota slot is reserved at inspection creation (including abandoned uploads).
There are no visitor accounts: IDs from the same active window are capabilities.
"""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
import inspect
import json
import time
from uuid import uuid4

from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
from fastapi import HTTPException

VERSION = "rentready-public-mode/1.0"
CONTROL_KEY = {"PK": "INSPECTION#PUBLIC_MODE_CONTROL", "SK": "SETTINGS"}
MAX_PUBLIC_BYTES = 500_000_000
public_context: ContextVar[dict | None] = ContextVar("public_judging_context", default=None)


def _table():
    from .aws import table
    return table


def _client():
    from .aws import session
    return session.client("dynamodb")


def _encode(item):
    serializer = TypeSerializer()
    return {key: serializer.serialize(value) for key, value in item.items()}


def control():
    return _table().get_item(Key=CONTROL_KEY, ConsistentRead=True).get("Item", {})


def active(value, now=None):
    try:
        return (value.get("schema_version") == VERSION
                and value.get("enabled") is True
                and bool(value.get("window_id"))
                and int(value["expires_at_epoch"]) > (time.time() if now is None else now)
                and 0 < int(value["max_upload_bytes"]) <= MAX_PUBLIC_BYTES
                and int(value["max_inspections"]) > 0
                and int(value["admitted_count"]) >= 0)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def status_document(value):
    available = active(value)
    return {"schema_version": VERSION, "public_access": available,
            "expires_at_epoch": int(value.get("expires_at_epoch", 0)),
            "max_upload_bytes": int(value.get("max_upload_bytes", MAX_PUBLIC_BYTES)),
            "max_inspections": int(value.get("max_inspections", 0)),
            "admitted_inspections": int(value.get("admitted_count", 0)),
            "remaining_inspections": max(0, int(value.get("max_inspections", 0))
                                         - int(value.get("admitted_count", 0)))}


def _live_condition(value):
    return {"ConditionExpression": "#enabled = :yes AND #window = :window AND #expiry > :now",
            "ExpressionAttributeNames": {"#enabled": "enabled", "#window": "window_id",
                                         "#expiry": "expires_at_epoch"},
            "ExpressionAttributeValues": {":yes": True, ":window": value["window_id"],
                                          ":now": int(time.time())}}


def _conditional_failure(exc):
    error = exc.response.get("Error", {}).get("Code")
    return (error == "ConditionalCheckFailedException"
            or (error == "TransactionCanceledException" and any(
                row.get("Code") == "ConditionalCheckFailed"
                for row in exc.response.get("CancellationReasons", []))))


def create_public_inspection(inspection_id, *, purpose, property_label):
    value = public_context.get()
    if not value or not active(value):
        raise HTTPException(401, "Public access is disabled or expired")
    from .db import utc_now, inspection_pk
    now = utc_now()
    item = {"PK": inspection_pk(inspection_id), "SK": "METADATA", "entity_type": "inspection",
            "inspection_id": inspection_id, "status": "CREATED", "purpose": purpose,
            "property_label": property_label, "created_at": now, "updated_at": now,
            "public_window_id": value["window_id"],
            "public_max_upload_bytes": int(value["max_upload_bytes"])}
    guard = _live_condition(value)
    guard["ConditionExpression"] += " AND #used < #limit AND #revision = :revision"
    guard["ExpressionAttributeNames"].update({"#used": "admitted_count", "#limit": "max_inspections",
                                             "#revision": "revision"})
    guard["ExpressionAttributeValues"].update({":one": 1, ":revision": value["revision"]})
    transaction = [
        {"Update": {"TableName": _table().name, "Key": _encode(CONTROL_KEY),
                    "UpdateExpression": "ADD #used :one", **guard,
                    "ExpressionAttributeValues": _encode(guard["ExpressionAttributeValues"])}},
        {"Put": {"TableName": _table().name, "Item": _encode(item),
                 "ConditionExpression": "attribute_not_exists(PK)"}},
    ]
    try:
        _client().transact_write_items(TransactItems=transaction, ClientRequestToken=inspection_id)
    except ClientError as exc:
        if _conditional_failure(exc):
            raise HTTPException(429, "Public inspection quota reached or settings changed; refresh the page") from None
        raise
    return item


def upload_limit(default):
    value = public_context.get()
    return min(default, int(value["max_upload_bytes"]), MAX_PUBLIC_BYTES) if value else default


def url_ttl(default):
    value = public_context.get()
    if not value:
        return default
    remaining = int(value["expires_at_epoch"]) - int(time.time())
    if remaining < 1:
        raise HTTPException(401, "Public access has expired")
    return min(default, remaining)


def once_public(operation):
    """One execution per operation per admitted inspection; durable across restarts.

    Response loss can be retried from the saved response. A failed/in-flight
    operation cannot be started again publicly; the operator can recover it.
    """
    def decorate(function):
        signature = inspect.signature(function, eval_str=True)
        @wraps(function)
        def wrapped(*args, **kwargs):
            value = public_context.get()
            if value is None:
                return function(*args, **kwargs)
            arguments = signature.bind(*args, **kwargs)
            arguments.apply_defaults()
            inspection_id = arguments.arguments["inspection_id"]
            payload = arguments.arguments.get("payload")
            if payload is not None and payload.model_dump() != type(payload)().model_dump():
                raise HTTPException(403, "Public access uses the standard analysis settings")
            if arguments.arguments.get("force"):
                raise HTTPException(403, "Forced analysis requires operator access")
            key = {"PK": "INSPECTION#" + inspection_id, "SK": "METADATA"}
            operation_key = {"PK": key["PK"], "SK": "PUBLIC_OPERATION#" + operation}
            claim = uuid4().hex
            guard = _live_condition(value)
            try:
                _client().transact_write_items(TransactItems=[
                    {"ConditionCheck": {"TableName": _table().name, "Key": _encode(CONTROL_KEY),
                                        **guard, "ExpressionAttributeValues": _encode(guard["ExpressionAttributeValues"])}},
                    {"ConditionCheck": {"TableName": _table().name, "Key": _encode(key),
                                        "ConditionExpression": "public_window_id = :window",
                                        "ExpressionAttributeValues": _encode({":window": value["window_id"]})}},
                    {"Put": {"TableName": _table().name,
                             "Item": _encode({**operation_key, "claim": claim, "public_window_id": value["window_id"]}),
                             "ConditionExpression": "attribute_not_exists(PK)"}},
                ], ClientRequestToken=claim)
            except ClientError as exc:
                if not _conditional_failure(exc):
                    raise
                saved = _table().get_item(Key=operation_key, ConsistentRead=True).get("Item", {})
                current = control()
                if (not active(current) or current.get("window_id") != value["window_id"]
                        or saved.get("public_window_id") != value["window_id"]):
                    raise HTTPException(401, "Public access is disabled or expired") from None
                if "response_json" in saved:
                    return json.loads(saved["response_json"])
                raise HTTPException(409, "This public operation is already running or needs operator recovery") from None
            # Leave a durable claim on failure; never silently repeat expensive work.
            result = function(*args, **kwargs)
            document = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            response_json = json.dumps(document, separators=(",", ":"), allow_nan=False)
            if len(response_json.encode()) > 64_000:
                raise HTTPException(503, "Public operation result needs operator recovery")
            _table().update_item(Key=operation_key, UpdateExpression="SET response_json = :result",
                                 ConditionExpression="#claim = :claim",
                                 ExpressionAttributeNames={"#claim": "claim"},
                                 ExpressionAttributeValues={":claim": claim, ":result": response_json})
            return result
        wrapped.__signature__ = signature
        return wrapped
    return decorate
