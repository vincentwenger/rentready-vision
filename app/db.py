from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from botocore.exceptions import ClientError
from boto3.dynamodb.types import TypeSerializer
from .aws import table, session


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



class CancellationConflict(RuntimeError):
    """Inspection changed or cannot be canceled in its current state."""



def request_agent_job_cancellation(
    inspection_id: str,
) -> dict[str, Any]:
    """Request cancellation of the active follow-up agent job.

    Preserve the completed primary inspection and its evidence.
    The worker must separately acknowledge and finish cancellation.
    """
    item = get_inspection(inspection_id)

    if item is None:
        raise KeyError(inspection_id)

    if item.get("status") != "COMPLETE":
        raise CancellationConflict(
            "Primary inspection is not complete"
        )

    agent_status = item.get("agentic_status")

    if agent_status in {
        "CANCEL_REQUESTED", "CANCELLED",
    }:
        return item

    if agent_status not in {
        "PENDING_ENQUEUE",
        "QUEUED",
        "RETRY_PENDING",
        "PROCESSING",
    }:
        raise CancellationConflict(
            "No cancellable agent job is active"
        )

    job_id = item.get("active_agent_job_id")

    if not job_id:
        raise CancellationConflict(
            "Active agent job identity is unavailable"
        )

    now = utc_now()

    try:
        result = table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression=(
                "SET #agent_status = :requested, "
                "#requested_at = :now, #updated = :now"
            ),
            ConditionExpression=(
                "#primary_status = :complete AND "
                "#agent_status = :expected AND "
                "#agent_job = :job AND "
                "#updated = :previous"
            ),
            ExpressionAttributeNames={
                "#primary_status": "status",
                "#agent_status": "agentic_status",
                "#agent_job": "active_agent_job_id",
                "#requested_at": "agentic_cancellation_requested_at",
                "#updated": "updated_at",
            },
            ExpressionAttributeValues={
                ":complete": "COMPLETE",
                ":expected": agent_status,
                ":requested": "CANCEL_REQUESTED",
                ":job": job_id,
                ":previous": item["updated_at"],
                ":now": now,
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            raise CancellationConflict(
                "Agent job changed during cancellation; retry"
            ) from exc
        raise

    return _json_safe(result["Attributes"])

def request_inspection_cancellation(
    inspection_id: str,
) -> dict[str, Any]:
    """Record cancellation with a conditional DynamoDB update.

    This records cancellation intent. An active worker must separately
    acknowledge cancellation before the inspection becomes CANCELLED.
    """
    item = get_inspection(inspection_id)

    if item is None:
        raise KeyError(inspection_id)

    current = item["status"]

    if current in {"CANCEL_REQUESTED", "CANCELLED"}:
        return item

    before_processing = {
        "CREATED", "UPLOAD_PENDING", "UPLOADED",
    }
    active_processing = {
        "QUEUED", "RETRY_PENDING", "PROCESSING",
    }

    if current in before_processing:
        if item.get("active_job_id"):
            raise CancellationConflict(
                "Inspection has an unexpected active job"
            )
        next_status = "CANCELLED"

    elif current in active_processing:
        if not item.get("active_job_id"):
            raise CancellationConflict(
                "Processing job identity is unavailable"
            )
        next_status = "CANCEL_REQUESTED"

    else:
        raise CancellationConflict(
            f"Cannot cancel inspection in status {current}"
        )

    now = utc_now()

    expression = (
        "SET #status = :next, #updated = :now, "
        "#requested = :now"
    )

    names = {
        "#status": "status",
        "#updated": "updated_at",
        "#requested": "cancellation_requested_at",
        "#active": "active_job_id",
    }

    values = {
        ":next": next_status,
        ":expected": current,
        ":previous": item["updated_at"],
        ":now": now,
    }

    if next_status == "CANCELLED":
        expression += ", #completed = :now"
        names["#completed"] = "cancellation_completed_at"
        job_guard = "attribute_not_exists(#active)"
    else:
        values[":job"] = item["active_job_id"]
        job_guard = "#active = :job"

    try:
        result = table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression=expression,
            ConditionExpression=(
                "#status = :expected AND "
                "#updated = :previous AND "
                + job_guard
            ),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            raise CancellationConflict(
                "Inspection changed during cancellation; retry"
            ) from exc
        raise

    return _json_safe(result["Attributes"])


def update_inspection_if_status(
    inspection_id: str,
    *,
    expected_statuses: tuple[str, ...],
    **changes: Any,
) -> dict[str, Any]:
    """Conditionally update an inspection that has not started processing.

    Prevents an in-flight upload operation from overwriting a user
    cancellation or taking over an inspection with an active job.
    """
    if not expected_statuses:
        raise ValueError("At least one expected status is required")

    if "status" not in changes:
        raise ValueError("The next inspection status is required")

    if "updated_at" in changes:
        raise ValueError("updated_at is managed by the database")

    updates = {**changes, "updated_at": utc_now()}

    names = {
        "#current": "status",
        "#active": "active_job_id",
    }
    values = {}
    assignments = []

    for index, (field, value) in enumerate(updates.items()):
        name = f"#field{index}"
        token = f":value{index}"
        names[name] = field
        values[token] = _ddb_safe(value)
        assignments.append(f"{name} = {token}")

    expected_tokens = []

    for index, expected in enumerate(expected_statuses):
        token = f":expected{index}"
        expected_tokens.append(token)
        values[token] = expected

    condition = (
        "attribute_exists(PK) AND "
        "#current IN (" + ", ".join(expected_tokens) + ") "
        "AND attribute_not_exists(#active)"
    )

    try:
        result = table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            raise CancellationConflict(
                "Inspection state changed; transition refused"
            ) from exc
        raise

    return _json_safe(result["Attributes"])

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



def create_queued_processing_job(
    inspection_id: str,
    job: dict[str, Any],
    *,
    backend: str,
) -> dict[str, Any]:
    """Atomically create a job and queue an uploaded inspection.

    A cancellation before this transaction prevents job creation.
    A cancellation afterward sees the exact active job ID.
    """
    now = utc_now()
    job_id = str(job["job_id"])

    record = {
        "PK": inspection_pk(inspection_id),
        "SK": processing_job_sk(job_id),
        "entity_type": "processing_job",
        "inspection_id": inspection_id,
        "job_id": job_id,
        "operation": str(job["operation"]),
        "status": "PENDING_ENQUEUE",
        "message_schema_version": str(job["schema_version"]),
        "runtime_schema_version": str(
            job["runtime_schema_version"]
        ),
        "git_commit": str(job["git_commit"]),
        "s3_input_key": str(job["s3_input_key"]),
        "source_etag": job.get("source_etag"),
        "processing_parameters": _ddb_safe(
            job["processing_parameters"]
        ),
        "created_at": now,
        "updated_at": now,
        "attempt_count": 0,
    }

    metadata = {
        "status": "QUEUED",
        "error": None,
        "active_job_id": job_id,
        "processing_backend": backend,
        "processing_operation": job["operation"],
        "processing_message_schema_version": job[
            "schema_version"
        ],
        "processing_runtime_schema_version": job[
            "runtime_schema_version"
        ],
        "processing_git_commit": job["git_commit"],
        "updated_at": now,
    }

    serializer = TypeSerializer()

    def encode(values: dict[str, Any]) -> dict[str, Any]:
        return {
            name: serializer.serialize(_ddb_safe(value))
            for name, value in values.items()
        }

    names = {
        "#current": "status",
        "#active": "active_job_id",
    }
    values = {":uploaded": "UPLOADED"}
    assignments = []

    for index, (field, value) in enumerate(metadata.items()):
        name = f"#field{index}"
        token = f":value{index}"
        names[name] = field
        values[token] = value
        assignments.append(f"{name} = {token}")

    transaction = [
        {
            "Put": {
                "TableName": table.name,
                "Item": encode(record),
                "ConditionExpression": (
                    "attribute_not_exists(PK)"
                ),
            },
        },
        {
            "Update": {
                "TableName": table.name,
                "Key": encode({
                    "PK": inspection_pk(inspection_id),
                    "SK": "METADATA",
                }),
                "UpdateExpression": (
                    "SET " + ", ".join(assignments)
                ),
                "ConditionExpression": (
                    "attribute_exists(PK) AND "
                    "#current = :uploaded AND "
                    "attribute_not_exists(#active)"
                ),
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": encode(values),
            },
        },
    ]

    try:
        session.client("dynamodb").transact_write_items(
            TransactItems=transaction,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        reasons = (
            exc.response.get("CancellationReasons") or []
        )

        if (
            code == "TransactionCanceledException"
            and any(
                reason.get("Code") == "ConditionalCheckFailed"
                for reason in reasons
            )
        ):
            raise CancellationConflict(
                "Inspection was canceled, changed, "
                "or already has a processing job"
            ) from exc

        raise

    return _json_safe(record)


def ensure_processing_dispatch_allowed(
    inspection_id: str,
    job_id: str,
) -> None:
    """Reject SQS dispatch if this inspection or job changed.

    Both existing database readers use strongly consistent reads.
    No records are modified by this check.
    """
    inspection = get_inspection(inspection_id)

    if (
        not inspection
        or inspection.get("status") != "QUEUED"
        or inspection.get("active_job_id") != job_id
    ):
        raise CancellationConflict(
            "Inspection was canceled or is no longer "
            "queued for this job"
        )

    job = get_processing_job(inspection_id, job_id)

    if (
        not job
        or job.get("status") != "PENDING_ENQUEUE"
        or job.get("job_id") != job_id
    ):
        raise CancellationConflict(
            "Processing job is no longer pending dispatch"
        )

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



def mark_inspection_queued(
    inspection_id: str,
    job: dict[str, Any],
    *,
    backend: str,
) -> dict[str, Any]:
    """Requeue only the expected job in an eligible inspection state.

    Cancellation must never be overwritten by a retry.
    """
    fields = {
        "status": "QUEUED",
        "error": None,
        "active_job_id": job["job_id"],
        "processing_backend": backend,
        "processing_operation": job["operation"],
        "processing_message_schema_version": job["schema_version"],
        "processing_runtime_schema_version": job["runtime_schema_version"],
        "processing_git_commit": job["git_commit"],
        "updated_at": utc_now(),
    }

    names = {
        "#current": "status",
        "#active": "active_job_id",
    }
    values = {
        ":job": job["job_id"],
        ":failed": "FAILED",
        ":complete": "COMPLETE",
        ":queued": "QUEUED",
        ":retry": "RETRY_PENDING",
        ":processing": "PROCESSING",
    }
    assignments = []

    for index, (field, value) in enumerate(fields.items()):
        name = f"#field{index}"
        token = f":value{index}"
        names[name] = field
        values[token] = _ddb_safe(value)
        assignments.append(f"{name} = {token}")

    try:
        result = table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression=(
                "#active = :job AND "
                "#current IN "
                "(:failed, :complete, :queued, :retry, :processing)"
            ),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            raise CancellationConflict(
                "Inspection was canceled or changed during retry"
            ) from exc
        raise

    return _json_safe(result["Attributes"])

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
                "#attempts = if_not_exists(#attempts, :zero) + :one REMOVE #progress"
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
                "#progress": "progress",
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




def finalize_queued_processing_cancellation(
    inspection_id: str,
    job_id: str,
) -> bool:
    """Cancel an unclaimed job without interrupting an active worker.

    A job is marked CANCELLED first so a subsequent SQS delivery cannot
    claim it. The metadata update can be safely retried.
    """
    item = get_inspection(inspection_id)

    if not item or item.get("active_job_id") != job_id:
        return False

    if item.get("status") not in {
        "CANCEL_REQUESTED", "CANCELLED",
    }:
        return False

    job = get_processing_job(inspection_id, job_id)

    if not job:
        return False

    if job.get("status") != "CANCELLED":
        if job.get("status") not in {
            "PENDING_ENQUEUE", "QUEUED", "RETRY_PENDING",
        }:
            return False

        now = utc_now()

        try:
            table.update_item(
                Key={
                    "PK": inspection_pk(inspection_id),
                    "SK": processing_job_sk(job_id),
                },
                UpdateExpression=(
                    "SET #status = :cancelled, "
                    "#updated = :now, #cancelled_at = :now"
                ),
                ConditionExpression=(
                    "#job_id = :job AND "
                    "#status IN (:pending, :queued, :retry)"
                ),
                ExpressionAttributeNames={
                    "#status": "status",
                    "#updated": "updated_at",
                    "#cancelled_at": "cancellation_acknowledged_at",
                    "#job_id": "job_id",
                },
                ExpressionAttributeValues={
                    ":job": job_id,
                    ":cancelled": "CANCELLED",
                    ":pending": "PENDING_ENQUEUE",
                    ":queued": "QUEUED",
                    ":retry": "RETRY_PENDING",
                    ":now": now,
                },
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == (
                "ConditionalCheckFailedException"
            ):
                return False
            raise

    try:
        table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression=(
                "SET #status = :cancelled, "
                "#updated = :now, #completed = :now, "
                "#event = :event"
            ),
            ConditionExpression=(
                "#status = :requested AND #active = :job"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#updated": "updated_at",
                "#completed": "cancellation_completed_at",
                "#event": "last_processing_event",
                "#active": "active_job_id",
            },
            ExpressionAttributeValues={
                ":requested": "CANCEL_REQUESTED",
                ":cancelled": "CANCELLED",
                ":job": job_id,
                ":now": utc_now(),
                ":event": "PROCESSING_CANCELLED",
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != (
            "ConditionalCheckFailedException"
        ):
            raise

        latest = get_inspection(inspection_id)
        return bool(
            latest
            and latest.get("status") == "CANCELLED"
            and latest.get("active_job_id") == job_id
        )

    return True



def finalize_queued_agent_cancellation(
    inspection_id: str,
    job_id: str,
) -> bool:
    """Cancel an unclaimed agent job and preserve primary evidence.

    Update the job first so an SQS delivery cannot claim it.
    Then finalize agent metadata. A later call can reconcile
    an interruption between these updates.
    """
    item = get_inspection(inspection_id)

    if not item or item.get("status") != "COMPLETE":
        return False

    if item.get("active_agent_job_id") != job_id:
        return False

    if item.get("agentic_status") not in {
        "CANCEL_REQUESTED", "CANCELLED",
    }:
        return False

    job = get_processing_job(inspection_id, job_id)

    if not job or job.get("job_id") != job_id:
        return False

    if job.get("status") != "CANCELLED":
        if job.get("status") not in {
            "PENDING_ENQUEUE", "QUEUED", "RETRY_PENDING",
        }:
            # A running job must stop itself before acknowledgment.
            return False

        now = utc_now()

        try:
            table.update_item(
                Key={
                    "PK": inspection_pk(inspection_id),
                    "SK": processing_job_sk(job_id),
                },
                UpdateExpression=(
                    "SET #status = :cancelled, "
                    "#updated = :now, #ack = :now"
                ),
                ConditionExpression=(
                    "#job = :job AND "
                    "#status IN (:pending, :queued, :retry)"
                ),
                ExpressionAttributeNames={
                    "#status": "status",
                    "#updated": "updated_at",
                    "#ack": "cancellation_acknowledged_at",
                    "#job": "job_id",
                },
                ExpressionAttributeValues={
                    ":job": job_id,
                    ":cancelled": "CANCELLED",
                    ":pending": "PENDING_ENQUEUE",
                    ":queued": "QUEUED",
                    ":retry": "RETRY_PENDING",
                    ":now": now,
                },
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == (
                "ConditionalCheckFailedException"
            ):
                return False
            raise

    # The job is durably canceled. Finalize only the agent state.
    # Never change the primary inspection's COMPLETE status.
    try:
        table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression=(
                "SET #agent_status = :cancelled, "
                "#updated = :now, #completed = :now, "
                "#event = :event"
            ),
            ConditionExpression=(
                "#primary = :complete AND "
                "#agent_status = :requested AND "
                "#agent_job = :job"
            ),
            ExpressionAttributeNames={
                "#primary": "status",
                "#agent_status": "agentic_status",
                "#agent_job": "active_agent_job_id",
                "#updated": "updated_at",
                "#completed": "agentic_cancellation_completed_at",
                "#event": "last_agentic_event",
            },
            ExpressionAttributeValues={
                ":complete": "COMPLETE",
                ":requested": "CANCEL_REQUESTED",
                ":cancelled": "CANCELLED",
                ":job": job_id,
                ":now": utc_now(),
                ":event": "AGENT_TOOL_CANCELLED",
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != (
            "ConditionalCheckFailedException"
        ):
            raise

        latest = get_inspection(inspection_id)

        return bool(
            latest
            and latest.get("status") == "COMPLETE"
            and latest.get("agentic_status") == "CANCELLED"
            and latest.get("active_agent_job_id") == job_id
        )

    return True




def mark_agent_enqueue_failed_if_active(
    inspection_id: str,
    job_id: str,
    error: str,
) -> bool:
    """Record agent enqueue failure without overwriting cancellation.

    Only the same job in QUEUED state may transition to FAILED.
    The primary inspection must remain COMPLETE.
    """
    try:
        table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression=(
                "SET #agent_status = :failed, "
                "#agent_error = :error, "
                "#event = :event, "
                "#updated = :now"
            ),
            ConditionExpression=(
                "#primary = :complete AND "
                "#agent_status = :queued AND "
                "#agent_job = :job"
            ),
            ExpressionAttributeNames={
                "#primary": "status",
                "#agent_status": "agentic_status",
                "#agent_job": "active_agent_job_id",
                "#agent_error": "agentic_error",
                "#event": "last_agentic_event",
                "#updated": "updated_at",
            },
            ExpressionAttributeValues={
                ":complete": "COMPLETE",
                ":queued": "QUEUED",
                ":failed": "FAILED",
                ":job": job_id,
                ":error": error,
                ":event": "AGENT_TOOL_ENQUEUE_FAILED",
                ":now": utc_now(),
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            return False
        raise

    return True


def restore_cached_agent_completion_if_allowed(
    inspection_id: str,
    job_id: str,
    **agent_fields: Any,
) -> dict[str, Any]:
    """Publish a cached completed agent result without undoing cancellation.

    Cached results may be selected after a completed or failed
    investigation, but never while another job is active or canceled.
    """
    if not job_id:
        raise ValueError("Agent job ID is required")

    reserved = {
        "status",
        "agentic_status",
        "active_agent_job_id",
        "updated_at",
    }
    if reserved.intersection(agent_fields):
        raise ValueError("Cached result fields override guarded state")

    changes = {
        "agentic_status": "COMPLETE",
        "active_agent_job_id": job_id,
        **agent_fields,
        "updated_at": utc_now(),
    }

    names = {
        "#primary": "status",
        "#current_agent": "agentic_status",
    }
    values = {
        ":primary_complete": "COMPLETE",
        ":agent_complete": "COMPLETE",
        ":agent_failed": "FAILED",
    }
    assignments = []

    for index, (field, value) in enumerate(changes.items()):
        name = f"#field{index}"
        token = f":value{index}"

        names[name] = field
        values[token] = _ddb_safe(value)
        assignments.append(f"{name} = {token}")

    try:
        result = table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression=(
                "#primary = :primary_complete AND ("
                "attribute_not_exists(#current_agent) OR "
                "#current_agent IN (:agent_complete, :agent_failed)"
                ")"
            ),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            raise CancellationConflict(
                "Cached AI result cannot replace a canceled "
                "or active investigation"
            ) from exc
        raise

    return _json_safe(result["Attributes"])

def mark_agent_job_queued_if_allowed(
    inspection_id: str,
    job_id: str,
    **agent_fields: Any,
) -> dict[str, Any]:
    """Queue an agent job without overwriting cancellation.

    A new agent job may follow a completed or failed agent job.
    An already queued job may be retried only with the same ID.
    """
    reserved = {
        "status",
        "agentic_status",
        "active_agent_job_id",
        "updated_at",
    }

    if not job_id:
        raise ValueError("Agent job ID is required")

    if reserved.intersection(agent_fields):
        raise ValueError(
            "Agent fields cannot override guarded state"
        )

    updates = {
        "agentic_status": "QUEUED",
        "active_agent_job_id": job_id,
        **agent_fields,
        "updated_at": utc_now(),
    }

    names = {
        "#primary": "status",
        "#agent_status": "agentic_status",
        "#agent_job": "active_agent_job_id",
    }

    values = {
        ":complete": "COMPLETE",
        ":done": "COMPLETE",
        ":failed": "FAILED",
        ":pending": "PENDING_ENQUEUE",
        ":queued": "QUEUED",
        ":retry": "RETRY_PENDING",
        ":job": job_id,
    }

    assignments = []

    for index, (field, value) in enumerate(updates.items()):
        name = f"#field{index}"
        token = f":value{index}"

        names[name] = field
        values[token] = _ddb_safe(value)
        assignments.append(f"{name} = {token}")

    condition = (
        "#primary = :complete AND ("
        "attribute_not_exists(#agent_status) OR "
        "#agent_status IN (:done, :failed) OR "
        "(#agent_job = :job AND "
        "#agent_status IN (:pending, :queued, :retry))"
        ")"
    )

    try:
        result = table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            raise CancellationConflict(
                "Agent job was canceled, changed, "
                "or another job is already active"
            ) from exc
        raise

    return _json_safe(result["Attributes"])

def mark_agent_job_processing_if_active(
    inspection_id: str,
    job_id: str,
) -> bool:
    """Mark an agent job processing only if cancellation has not won.

    The completed primary inspection remains unchanged.
    """
    try:
        table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression=(
                "SET #agent_status = :processing, "
                "#event = :event, #updated = :now"
            ),
            ConditionExpression=(
                "#primary = :complete AND "
                "#agent_job = :job AND "
                "#agent_status IN "
                "(:pending, :queued, :retry, :processing)"
            ),
            ExpressionAttributeNames={
                "#primary": "status",
                "#agent_status": "agentic_status",
                "#agent_job": "active_agent_job_id",
                "#event": "last_agentic_event",
                "#updated": "updated_at",
            },
            ExpressionAttributeValues={
                ":complete": "COMPLETE",
                ":job": job_id,
                ":pending": "PENDING_ENQUEUE",
                ":queued": "QUEUED",
                ":retry": "RETRY_PENDING",
                ":processing": "PROCESSING",
                ":event": "AGENT_TOOL_STARTED",
                ":now": utc_now(),
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            return False
        raise

    return True

def acknowledge_agent_job_cancellation(
    inspection_id: str,
    job_id: str,
    *,
    claim_token: str,
) -> bool:
    """Acknowledge a stopped agent job without changing primary results.

    The worker must stop its own processing before invoking this.
    The job is finalized first; metadata can be reconciled on retry.
    """
    item = get_inspection(inspection_id)

    if not item:
        return False

    if item.get("status") != "COMPLETE":
        return False

    if item.get("active_agent_job_id") != job_id:
        return False

    if item.get("agentic_status") not in {
        "CANCEL_REQUESTED", "CANCELLED",
    }:
        return False

    now = utc_now()

    try:
        table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": processing_job_sk(job_id),
            },
            UpdateExpression=(
                "SET #status = :cancelled, "
                "#updated = :now, #ack = :now "
                "REMOVE #lease"
            ),
            ConditionExpression=(
                "#status = :processing AND #claim = :claim"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#updated": "updated_at",
                "#ack": "cancellation_acknowledged_at",
                "#lease": "lease_expires_at",
                "#claim": "claim_token",
            },
            ExpressionAttributeValues={
                ":processing": "PROCESSING",
                ":cancelled": "CANCELLED",
                ":claim": claim_token,
                ":now": now,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != (
            "ConditionalCheckFailedException"
        ):
            raise

        # An earlier attempt may have finalized the job but
        # failed before updating inspection metadata.
        existing = get_processing_job(inspection_id, job_id)

        if not existing or (
            existing.get("status") != "CANCELLED"
            or existing.get("claim_token") != claim_token
        ):
            return False

    try:
        table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression=(
                "SET #agent_status = :cancelled, "
                "#updated = :now, #completed = :now, "
                "#event = :event"
            ),
            ConditionExpression=(
                "#primary = :complete AND "
                "#agent_status = :requested AND "
                "#agent_job = :job"
            ),
            ExpressionAttributeNames={
                "#primary": "status",
                "#agent_status": "agentic_status",
                "#agent_job": "active_agent_job_id",
                "#updated": "updated_at",
                "#completed": "agentic_cancellation_completed_at",
                "#event": "last_agentic_event",
            },
            ExpressionAttributeValues={
                ":complete": "COMPLETE",
                ":requested": "CANCEL_REQUESTED",
                ":cancelled": "CANCELLED",
                ":job": job_id,
                ":now": utc_now(),
                ":event": "AGENT_TOOL_CANCELLED",
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != (
            "ConditionalCheckFailedException"
        ):
            raise

        latest = get_inspection(inspection_id)

        return bool(
            latest
            and latest.get("status") == "COMPLETE"
            and latest.get("agentic_status") == "CANCELLED"
            and latest.get("active_agent_job_id") == job_id
        )

    return True

def acknowledge_processing_cancellation(
    inspection_id: str,
    job_id: str,
    *,
    claim_token: str,
) -> bool:
    """A worker confirms cancellation after stopping its own work.

    First transition the exact claimed job, then its inspection.
    A repeated call can reconcile an interrupted second update.
    """
    item = get_inspection(inspection_id)
    if not item:
        return False

    if item.get("active_job_id") != job_id:
        return False

    if item.get("status") not in {
        "CANCEL_REQUESTED", "CANCELLED",
    }:
        return False

    now = utc_now()

    try:
        table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": processing_job_sk(job_id),
            },
            UpdateExpression=(
                "SET #status = :cancelled, #updated = :now, "
                "#acknowledged = :now REMOVE #lease"
            ),
            ConditionExpression=(
                "#status = :processing AND #claim = :claim"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#updated": "updated_at",
                "#acknowledged": "cancellation_acknowledged_at",
                "#lease": "lease_expires_at",
                "#claim": "claim_token",
            },
            ExpressionAttributeValues={
                ":processing": "PROCESSING",
                ":cancelled": "CANCELLED",
                ":claim": claim_token,
                ":now": now,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != (
            "ConditionalCheckFailedException"
        ):
            raise

        existing = get_processing_job(inspection_id, job_id)
        if not existing or (
            existing.get("status") != "CANCELLED"
            or existing.get("claim_token") != claim_token
        ):
            return False

    try:
        table.update_item(
            Key={
                "PK": inspection_pk(inspection_id),
                "SK": "METADATA",
            },
            UpdateExpression=(
                "SET #status = :cancelled, #updated = :now, "
                "#completed = :now, #event = :event"
            ),
            ConditionExpression=(
                "#status = :requested AND #active = :job"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#updated": "updated_at",
                "#completed": "cancellation_completed_at",
                "#event": "last_processing_event",
                "#active": "active_job_id",
            },
            ExpressionAttributeValues={
                ":requested": "CANCEL_REQUESTED",
                ":cancelled": "CANCELLED",
                ":job": job_id,
                ":now": utc_now(),
                ":event": "PROCESSING_CANCELLED",
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != (
            "ConditionalCheckFailedException"
        ):
            raise

        latest = get_inspection(inspection_id)
        return bool(
            latest
            and latest.get("status") == "CANCELLED"
            and latest.get("active_job_id") == job_id
        )

    return True

def _update_active_inspection_state(
    inspection_id: str,
    job_id: str,
    *,
    status: str,
    **changes: Any,
) -> bool:
    values: dict[str, Any] = {
        ":job": job_id,
        ":status": status,
        ":updated": utc_now(),
        ":cancel_requested": "CANCEL_REQUESTED",
        ":cancelled": "CANCELLED",
    }
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
            ConditionExpression=(
                "#active = :job AND "
                "#status <> :cancel_requested AND "
                "#status <> :cancelled"
            ),
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
    issue_report_metadata: dict[str, Any] | None = None,
) -> bool:
    """Atomically publish job and inspection completion.

    Cancellation and completion race on inspection status.
    Only one may commit.
    """
    now = utc_now()
    issue_fields = dict(issue_report_metadata or {})

    reserved = {
        "status", "error", "manifest_s3_key", "video",
        "processing", "processing_completed_at",
        "processing_telemetry", "last_processing_event",
        "updated_at",
    }
    if reserved.intersection(issue_fields):
        raise ValueError(
            "Issue metadata conflicts with completion fields"
        )

    serializer = TypeSerializer()

    def encoded(values: dict[str, Any]) -> dict[str, Any]:
        return {
            key: serializer.serialize(_ddb_safe(value))
            for key, value in values.items()
        }

    metadata_fields = {
        "status": "COMPLETE",
        "error": None,
        "manifest_s3_key": manifest_s3_key,
        "video": video,
        "processing": processing,
        "processing_completed_at": now,
        "processing_telemetry": telemetry,
        "last_processing_event": "PROCESSING_COMPLETE",
        "updated_at": now,
        **issue_fields,
    }

    meta_names = {
        "#active": "active_job_id",
        "#current": "status",
    }
    meta_values = {
        ":job": job_id,
        ":processing": "PROCESSING",
    }
    meta_clauses = []

    for i, (field, value) in enumerate(metadata_fields.items()):
        name = f"#field{i}"
        token = f":value{i}"
        meta_names[name] = field
        meta_values[token] = value
        meta_clauses.append(f"{name} = {token}")

    transaction = [
        {
            "Update": {
                "TableName": table.name,
                "Key": encoded({
                    "PK": inspection_pk(inspection_id),
                    "SK": processing_job_sk(job_id),
                }),
                "UpdateExpression": (
                    "SET #status = :complete, "
                    "#manifest = :manifest, "
                    "#completed = :now, #updated = :now, "
                    "#telemetry = :telemetry, #video = :video, "
                    "#processing_data = :processing_data, "
                    "#issue = :issue REMOVE #lease"
                ),
                "ConditionExpression": (
                    "#status = :processing AND #claim = :claim"
                ),
                "ExpressionAttributeNames": {
                    "#status": "status",
                    "#manifest": "manifest_s3_key",
                    "#completed": "completed_at",
                    "#updated": "updated_at",
                    "#telemetry": "telemetry",
                    "#video": "video",
                    "#processing_data": "processing",
                    "#issue": "issue_report_metadata",
                    "#lease": "lease_expires_at",
                    "#claim": "claim_token",
                },
                "ExpressionAttributeValues": encoded({
                    ":complete": "COMPLETE",
                    ":processing": "PROCESSING",
                    ":claim": claim_token,
                    ":manifest": manifest_s3_key,
                    ":now": now,
                    ":telemetry": telemetry,
                    ":video": video,
                    ":processing_data": processing,
                    ":issue": issue_fields,
                }),
            }
        },
        {
            "Update": {
                "TableName": table.name,
                "Key": encoded({
                    "PK": inspection_pk(inspection_id),
                    "SK": "METADATA",
                }),
                "UpdateExpression": (
                    "SET " + ", ".join(meta_clauses)
                ),
                "ConditionExpression": (
                    "#active = :job AND "
                    "#current = :processing"
                ),
                "ExpressionAttributeNames": meta_names,
                "ExpressionAttributeValues": encoded(meta_values),
            }
        },
    ]

    try:
        session.client("dynamodb").transact_write_items(
            TransactItems=transaction,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")

        if code == "TransactionCanceledException":
            reasons = (
                exc.response.get("CancellationReasons") or []
            )
            if any(
                reason.get("Code") == "ConditionalCheckFailed"
                for reason in reasons
            ):
                return False
        raise

    return True

def reconcile_completed_job(inspection_id: str, job_id: str, job: dict[str, Any]) -> bool:
    """Repair inspection metadata from an already-complete idempotent job."""
    manifest_s3_key = job.get("manifest_s3_key")
    if not manifest_s3_key:
        return False

    issue_report_metadata = dict(
        job.get("issue_report_metadata")
        or {}
    )

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
        **issue_report_metadata,
    )


def fail_agent_processing_attempt_if_allowed(
    inspection_id: str,
    job_id: str,
    *,
    claim_token: str,
    error: str,
    terminal: bool,
    receive_count: int,
) -> bool:
    """Atomically record an agent failure only while it is active.

    A cancellation request changing agentic_status prevents
    both writes. The primary inspection remains COMPLETE.
    """
    now = utc_now()
    next_status = "FAILED" if terminal else "RETRY_PENDING"
    serializer = TypeSerializer()

    def encode(values: dict[str, Any]) -> dict[str, Any]:
        return {
            key: serializer.serialize(_ddb_safe(value))
            for key, value in values.items()
        }

    transaction = [
        {
            "Update": {
                "TableName": table.name,
                "Key": encode({
                    "PK": inspection_pk(inspection_id),
                    "SK": processing_job_sk(job_id),
                }),
                "UpdateExpression": (
                    "SET #status = :next, #error = :error, "
                    "#updated = :now, #receive = :receive "
                    "REMOVE #claim, #lease"
                ),
                "ConditionExpression": (
                    "#status = :processing AND #claim = :claim"
                ),
                "ExpressionAttributeNames": {
                    "#status": "status",
                    "#error": "last_error",
                    "#updated": "updated_at",
                    "#receive": "sqs_receive_count",
                    "#claim": "claim_token",
                    "#lease": "lease_expires_at",
                },
                "ExpressionAttributeValues": encode({
                    ":next": next_status,
                    ":error": error,
                    ":now": now,
                    ":receive": receive_count,
                    ":processing": "PROCESSING",
                    ":claim": claim_token,
                }),
            },
        },
        {
            "Update": {
                "TableName": table.name,
                "Key": encode({
                    "PK": inspection_pk(inspection_id),
                    "SK": "METADATA",
                }),
                "UpdateExpression": (
                    "SET #agent_status = :next, "
                    "#agent_error = :error, "
                    "#event = :event, #updated = :now"
                ),
                "ConditionExpression": (
                    "#primary = :complete AND "
                    "#agent_status = :processing AND "
                    "#agent_job = :job"
                ),
                "ExpressionAttributeNames": {
                    "#primary": "status",
                    "#agent_status": "agentic_status",
                    "#agent_job": "active_agent_job_id",
                    "#agent_error": "agentic_error",
                    "#event": "last_agentic_event",
                    "#updated": "updated_at",
                },
                "ExpressionAttributeValues": encode({
                    ":complete": "COMPLETE",
                    ":processing": "PROCESSING",
                    ":job": job_id,
                    ":next": next_status,
                    ":error": error,
                    ":event": "AGENT_TOOL_FAILED",
                    ":now": now,
                }),
            },
        },
    ]

    try:
        session.client("dynamodb").transact_write_items(
            TransactItems=transaction
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")

        if code == "TransactionCanceledException":
            reasons = (
                exc.response.get("CancellationReasons") or []
            )

            if any(
                reason.get("Code") == "ConditionalCheckFailed"
                for reason in reasons
            ):
                return False

        # Unexpected AWS errors must not be mistaken
        # for successful cancellation.
        raise

    return True

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
    """Atomically complete an agent job and update its metadata.

    Both writes must succeed together. A cancellation request
    changing agentic_status prevents either completion write.
    The primary inspection remains COMPLETE.
    """
    now = utc_now()
    serializer = TypeSerializer()

    def encode(values: dict[str, Any]) -> dict[str, Any]:
        return {
            key: serializer.serialize(_ddb_safe(value))
            for key, value in values.items()
        }

    job_fields = {
        "status": "COMPLETE",
        "result_s3_key": result_s3_key,
        "completed_at": now,
        "updated_at": now,
        "telemetry": telemetry,
        "agent_result": result,
    }

    metadata_fields = {
        "agentic_status": "COMPLETE",
        "agentic_error": None,
        "active_agent_job_id": job_id,
        "agentic_trace_s3_key": result_s3_key,
        "agentic_confidence_before": result.get(
            "confidence_before"
        ),
        "agentic_confidence_after": result.get(
            "confidence_after"
        ),
        "agentic_action": result.get("action"),
        "agentic_completed_at": now,
        "last_agentic_event": (
            result.get("completion_event")
            or "AGENT_ACTION_DECIDED"
        ),
        "updated_at": now,
    }

    def assignments(fields):
        names = {}
        values = {}
        parts = []

        for index, (field, value) in enumerate(fields.items()):
            alias = f"#field{index}"
            token = f":value{index}"
            names[alias] = field
            values[token] = value
            parts.append(f"{alias} = {token}")

        return names, values, "SET " + ", ".join(parts)

    job_names, job_values, job_update = assignments(
        job_fields
    )

    job_names.update({
        "#claim": "claim_token",
        "#lease": "lease_expires_at",
    })
    job_values.update({
        ":processing": "PROCESSING",
        ":claim": claim_token,
    })

    meta_names, meta_values, meta_update = assignments(
        metadata_fields
    )

    meta_names.update({
        "#primary": "status",
        "#current_agent": "agentic_status",
        "#agent_job": "active_agent_job_id",
    })
    meta_values.update({
        ":complete": "COMPLETE",
        ":processing": "PROCESSING",
        ":job": job_id,
    })

    transaction = [
        {
            "Update": {
                "TableName": table.name,
                "Key": encode({
                    "PK": inspection_pk(inspection_id),
                    "SK": processing_job_sk(job_id),
                }),
                "UpdateExpression": (
                    job_update + " REMOVE #lease"
                ),
                "ConditionExpression": (
                    "#field0 = :processing AND "
                    "#claim = :claim"
                ),
                "ExpressionAttributeNames": job_names,
                "ExpressionAttributeValues": encode(job_values),
            },
        },
        {
            "Update": {
                "TableName": table.name,
                "Key": encode({
                    "PK": inspection_pk(inspection_id),
                    "SK": "METADATA",
                }),
                "UpdateExpression": meta_update,
                "ConditionExpression": (
                    "#primary = :complete AND "
                    "#current_agent = :processing AND "
                    "#agent_job = :job"
                ),
                "ExpressionAttributeNames": meta_names,
                "ExpressionAttributeValues": encode(meta_values),
            },
        },
    ]

    try:
        session.client("dynamodb").transact_write_items(
            TransactItems=transaction
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")

        if code == "TransactionCanceledException":
            reasons = (
                exc.response.get("CancellationReasons") or []
            )

            if any(
                reason.get("Code") == "ConditionalCheckFailed"
                for reason in reasons
            ):
                return False

        raise

    return True

def update_processing_progress(inspection_id: str, job_id: str, *, claim_token: str,
                               progress: dict[str, Any]) -> bool:
    """Only the current live attempt may publish progress for this durable job."""
    try:
        table.update_item(
            Key={"PK": inspection_pk(inspection_id), "SK": processing_job_sk(job_id)},
            UpdateExpression="SET #progress = :progress",
            ConditionExpression="#status = :processing AND #claim = :claim AND #lease >= :now",
            ExpressionAttributeNames={"#progress": "progress", "#status": "status",
                                      "#claim": "claim_token", "#lease": "lease_expires_at"},
            ExpressionAttributeValues={":progress": _ddb_safe(progress), ":processing": "PROCESSING",
                                       ":claim": claim_token, ":now": utc_now()},
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
