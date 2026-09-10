from __future__ import annotations

from datetime import datetime, timedelta, timezone
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



def processing_job_sk(job_id: str) -> str:
    return f"JOB#{job_id}"


def get_processing_job(inspection_id: str, job_id: str) -> dict[str, Any] | None:
    result = table.get_item(
        Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(job_id)},
        ConsistentRead=True,
    )
    item = result.get("Item")
    return _json_safe(item) if item else None


def prepare_processing_job(inspection_id: str, job: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Create a durable job record, or safely reuse/requeue the deterministic job.

    Returns (job_record, should_enqueue). Duplicate active/completed requests do not
    create a second logical job; failed enqueue/processing records can be requeued.
    """
    now = utc_now()
    item = {
        "PK": inspection_pk(inspection_id),
        "SK": processing_job_sk(str(job["job_id"])),
        "entity_type": "processing_job",
        "inspection_id": inspection_id,
        "job_id": str(job["job_id"]),
        "operation": str(job["operation"]),
        "status": "PENDING_ENQUEUE",
        "message_schema_version": str(job["schema_version"]),
        "runtime_schema_version": str(job["runtime_schema_version"]),
        "git_commit": str(job["git_commit"]),
        "s3_input_key": str(job["s3_input_key"]),
        "source_etag": job.get("source_etag"),
        "processing_parameters": _ddb_safe(job["processing_parameters"]),
        "created_at": now,
        "updated_at": now,
        "attempt_count": 0,
    }
    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
        return _json_safe(item), True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise

    existing = get_processing_job(inspection_id, str(job["job_id"]))
    if not existing:
        raise RuntimeError("Processing job disappeared after a conditional create conflict")
    if existing.get("status") in {"FAILED", "ENQUEUE_FAILED"}:
        result = table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(str(job["job_id"]))},
            UpdateExpression=(
                "SET #status = :queued, #updated = :now, #last_error = :none "
                "REMOVE #claim, #lease"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#updated": "updated_at",
                "#last_error": "last_error",
                "#claim": "claim_token",
                "#lease": "lease_expires_at",
            },
            ExpressionAttributeValues={":queued": "PENDING_ENQUEUE", ":now": now, ":none": None},
            ReturnValues="ALL_NEW",
        )
        return _json_safe(result["Attributes"]), True
    if existing.get("status") == "PENDING_ENQUEUE":
        return existing, True
    return existing, False


def mark_processing_job_enqueued(inspection_id: str, job_id: str, message_id: str | None) -> None:
    try:
        table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(job_id)},
            UpdateExpression="SET #status = :queued, #message = :message, #updated = :now",
            ConditionExpression="#status = :pending",
            ExpressionAttributeNames={
                "#status": "status",
                "#message": "sqs_message_id",
                "#updated": "updated_at",
            },
            ExpressionAttributeValues={
                ":queued": "QUEUED",
                ":pending": "PENDING_ENQUEUE",
                ":message": message_id,
                ":now": utc_now(),
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise


def mark_inspection_queued(inspection_id: str, job: dict[str, Any], *, backend: str) -> dict[str, Any]:
    return update_inspection(
        inspection_id,
        status="QUEUED",
        error=None,
        active_job_id=job["job_id"],
        processing_backend=backend,
        processing_operation=job["operation"],
        processing_message_schema_version=job["schema_version"],
        processing_runtime_schema_version=job["runtime_schema_version"],
        processing_git_commit=job["git_commit"],
    )


def mark_enqueue_failed(inspection_id: str, job_id: str, error: str) -> None:
    """Record an enqueue error without making the deterministic job unclaimable.

    A SendMessage client error can be ambiguous (AWS may have accepted the
    message). Leaving the job PENDING_ENQUEUE lets an accepted delivery run and
    lets a client retry safely enqueue the same job_id again.
    """
    now = utc_now()
    try:
        table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(job_id)},
            UpdateExpression="SET #error = :error, #updated = :now",
            ConditionExpression="#status = :pending",
            ExpressionAttributeNames={
                "#status": "status",
                "#error": "last_error",
                "#updated": "updated_at",
            },
            ExpressionAttributeValues={
                ":pending": "PENDING_ENQUEUE",
                ":error": error,
                ":now": now,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return
        raise
    _update_active_inspection_state(
        inspection_id,
        job_id,
        status="FAILED",
        error=error,
        last_processing_event="PROCESSING_FAILED",
    )


def _lease_timestamp(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def claim_processing_job(
    inspection_id: str,
    job_id: str,
    *,
    claim_token: str,
    lease_seconds: int,
    receive_count: int,
    worker_id: str,
) -> tuple[bool, dict[str, Any] | None]:
    now = utc_now()
    lease_expires = _lease_timestamp(lease_seconds)
    try:
        result = table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(job_id)},
            UpdateExpression=(
                "SET #status = :processing, #claim = :claim, #lease = :lease, "
                "#worker = :worker, #receive = :receive, #updated = :now, "
                "#attempts = if_not_exists(#attempts, :zero) + :one"
            ),
            ConditionExpression=(
                "#job_id = :job_id AND ("
                "#status IN (:pending, :queued, :retry) OR "
                "(#status = :processing AND (attribute_not_exists(#lease) OR #lease < :now))"
                ")"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#claim": "claim_token",
                "#lease": "lease_expires_at",
                "#worker": "worker_id",
                "#receive": "sqs_receive_count",
                "#updated": "updated_at",
                "#attempts": "attempt_count",
                "#job_id": "job_id",
            },
            ExpressionAttributeValues={
                ":processing": "PROCESSING",
                ":pending": "PENDING_ENQUEUE",
                ":queued": "QUEUED",
                ":retry": "RETRY_PENDING",
                ":claim": claim_token,
                ":lease": lease_expires,
                ":worker": worker_id,
                ":receive": receive_count,
                ":now": now,
                ":zero": 0,
                ":one": 1,
                ":job_id": job_id,
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False, get_processing_job(inspection_id, job_id)
        raise

    _update_active_inspection_state(
        inspection_id,
        job_id,
        status="PROCESSING",
        error=None,
        processing_started_at=now,
        worker_id=worker_id,
        last_processing_event="OPENCV_STARTED",
    )
    return True, _json_safe(result["Attributes"])


def extend_processing_lease(
    inspection_id: str,
    job_id: str,
    *,
    claim_token: str,
    lease_seconds: int,
) -> bool:
    try:
        table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(job_id)},
            UpdateExpression="SET #lease = :lease, #updated = :now",
            ConditionExpression="#status = :processing AND #claim = :claim",
            ExpressionAttributeNames={
                "#lease": "lease_expires_at",
                "#updated": "updated_at",
                "#status": "status",
                "#claim": "claim_token",
            },
            ExpressionAttributeValues={
                ":lease": _lease_timestamp(lease_seconds),
                ":now": utc_now(),
                ":processing": "PROCESSING",
                ":claim": claim_token,
            },
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _update_active_inspection_state(
    inspection_id: str,
    job_id: str,
    *,
    status: str,
    **changes: Any,
) -> bool:
    values: dict[str, Any] = {":job": job_id, ":status": status, ":updated": utc_now()}
    names: dict[str, str] = {
        "#active": "active_job_id",
        "#status": "status",
        "#updated": "updated_at",
    }
    parts = ["#status = :status", "#updated = :updated"]
    for index, (key, value) in enumerate(changes.items()):
        name = f"#c{index}"
        val = f":c{index}"
        names[name] = key
        values[val] = _ddb_safe(value)
        parts.append(f"{name} = {val}")
    try:
        table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": "METADATA"},
            UpdateExpression="SET " + ", ".join(parts),
            ConditionExpression="#active = :job",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def complete_processing_job(
    inspection_id: str,
    job_id: str,
    *,
    claim_token: str,
    manifest_s3_key: str,
    video: dict[str, Any],
    processing: dict[str, Any],
    telemetry: dict[str, Any],
) -> bool:
    now = utc_now()
    try:
        table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(job_id)},
            UpdateExpression=(
                "SET #status = :complete, #manifest = :manifest, #completed = :now, "
                "#updated = :now, #telemetry = :telemetry, #video = :video, "
                "#processing_data = :processing_data REMOVE #lease"
            ),
            ConditionExpression="#status = :processing AND #claim = :claim",
            ExpressionAttributeNames={
                "#status": "status",
                "#manifest": "manifest_s3_key",
                "#completed": "completed_at",
                "#updated": "updated_at",
                "#telemetry": "telemetry",
                "#video": "video",
                "#processing_data": "processing",
                "#lease": "lease_expires_at",
                "#claim": "claim_token",
            },
            ExpressionAttributeValues={
                ":complete": "COMPLETE",
                ":processing": "PROCESSING",
                ":claim": claim_token,
                ":manifest": manifest_s3_key,
                ":now": now,
                ":telemetry": _ddb_safe(telemetry),
                ":video": _ddb_safe(video),
                ":processing_data": _ddb_safe(processing),
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise

    return _update_active_inspection_state(
        inspection_id,
        job_id,
        status="COMPLETE",
        error=None,
        manifest_s3_key=manifest_s3_key,
        video=video,
        processing=processing,
        processing_completed_at=now,
        processing_telemetry=telemetry,
        last_processing_event="PROCESSING_COMPLETE",
    )



def reconcile_completed_job(inspection_id: str, job_id: str, job: dict[str, Any]) -> bool:
    """Repair inspection metadata from an already-complete idempotent job."""
    manifest_s3_key = job.get("manifest_s3_key")
    if not manifest_s3_key:
        return False
    return _update_active_inspection_state(
        inspection_id,
        job_id,
        status="COMPLETE",
        error=None,
        manifest_s3_key=manifest_s3_key,
        video=job.get("video"),
        processing=job.get("processing"),
        processing_telemetry=job.get("telemetry"),
        processing_completed_at=job.get("completed_at") or utc_now(),
        last_processing_event="PROCESSING_COMPLETE",
    )

def fail_processing_attempt(
    inspection_id: str,
    job_id: str,
    *,
    claim_token: str,
    error: str,
    terminal: bool,
    receive_count: int,
) -> bool:
    now = utc_now()
    next_status = "FAILED" if terminal else "RETRY_PENDING"
    try:
        table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(job_id)},
            UpdateExpression=(
                "SET #status = :next, #error = :error, #updated = :now, "
                "#receive = :receive REMOVE #claim, #lease"
            ),
            ConditionExpression="#status = :processing AND #claim = :claim",
            ExpressionAttributeNames={
                "#status": "status",
                "#error": "last_error",
                "#updated": "updated_at",
                "#receive": "sqs_receive_count",
                "#claim": "claim_token",
                "#lease": "lease_expires_at",
            },
            ExpressionAttributeValues={
                ":next": next_status,
                ":error": error,
                ":now": now,
                ":receive": receive_count,
                ":processing": "PROCESSING",
                ":claim": claim_token,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise

    return _update_active_inspection_state(
        inspection_id,
        job_id,
        status=next_status,
        error=error,
        processing_last_failed_at=now,
        processing_receive_count=receive_count,
        last_processing_event="PROCESSING_FAILED",
    )


def complete_agent_tool_job(
    inspection_id: str,
    job_id: str,
    *,
    claim_token: str,
    result_s3_key: str,
    result: dict[str, Any],
    telemetry: dict[str, Any],
) -> bool:
    """Complete a Step-18 agent tool without replacing the primary video manifest."""
    now = utc_now()
    try:
        table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(job_id)},
            UpdateExpression=(
                "SET #status = :complete, #result_key = :result_key, #completed = :now, "
                "#updated = :now, #telemetry = :telemetry, #agent_result = :agent_result "
                "REMOVE #lease"
            ),
            ConditionExpression="#status = :processing AND #claim = :claim",
            ExpressionAttributeNames={
                "#status": "status",
                "#result_key": "result_s3_key",
                "#completed": "completed_at",
                "#updated": "updated_at",
                "#telemetry": "telemetry",
                "#agent_result": "agent_result",
                "#lease": "lease_expires_at",
                "#claim": "claim_token",
            },
            ExpressionAttributeValues={
                ":complete": "COMPLETE",
                ":processing": "PROCESSING",
                ":claim": claim_token,
                ":result_key": result_s3_key,
                ":now": now,
                ":telemetry": _ddb_safe(telemetry),
                ":agent_result": _ddb_safe(result),
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise

    update_inspection(
        inspection_id,
        agentic_status="COMPLETE",
        agentic_error=None,
        active_agent_job_id=job_id,
        agentic_trace_s3_key=result_s3_key,
        agentic_confidence_before=result.get("confidence_before"),
        agentic_confidence_after=result.get("confidence_after"),
        agentic_action=result.get("action"),
        agentic_completed_at=now,
        last_agentic_event="AGENT_ACTION_DECIDED",
    )
    return True
