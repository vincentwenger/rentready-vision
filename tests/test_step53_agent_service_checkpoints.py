"""Step 53: cancellation inside AI service operations."""

import ast
import importlib
from pathlib import Path
from unittest.mock import Mock

import pytest


SERVICES = (
    "execute_interval_inspection_job",
    "execute_crop_region_job",
    "execute_enhance_region_job",
    "execute_other_angle_job",
    "execute_decision_policy_job",
)

EXPENSIVE_CALLS = {
    "download_file",
    "upload_file",
    "put_object",
    "inspect_interval",
    "inspect_other_angle",
    "write_crop_region",
    "write_enhanced_region",
    "reassess_interval_batches",
    "reassess_other_angle_evidence",
    "verify_candidate_image",
}


@pytest.mark.parametrize("name", SERVICES)
def test_service_accepts_optional_cancellation_callback(name):
    source = Path("app/services.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    )

    names = [arg.arg for arg in fn.args.kwonlyargs]

    assert "cancellation_check" in names

    index = names.index("cancellation_check")
    default = fn.args.kw_defaults[index]

    assert isinstance(default, ast.Constant)
    assert default.value is None


@pytest.mark.parametrize("name", SERVICES)
def test_expensive_service_operations_have_checkpoints(name):
    source = Path("app/services.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    )

    parents = {}

    for parent in ast.walk(fn):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    checked = 0

    for call in ast.walk(fn):
        if not isinstance(call, ast.Call):
            continue

        if isinstance(call.func, ast.Name):
            call_name = call.func.id
        elif isinstance(call.func, ast.Attribute):
            call_name = call.func.attr
        else:
            continue

        if call_name not in EXPENSIVE_CALLS:
            continue

        statement = call

        while (
            statement in parents
            and not isinstance(statement, ast.stmt)
        ):
            statement = parents[statement]

        container = parents[statement]

        block = next(
            (
                value for value in (
                    getattr(container, "body", []),
                    getattr(container, "orelse", []),
                    getattr(container, "finalbody", []),
                )
                if statement in value
            ),
            None,
        )

        assert block is not None

        position = block.index(statement)

        assert position > 0, (
            f"{name}: missing checkpoint before {call_name}"
        )

        guard = block[position - 1]

        assert isinstance(guard, ast.If), (
            f"{name}: no guard before {call_name}"
        )

        assert ast.unparse(guard.test) == (
            "cancellation_check is not None"
        ), f"{name}: unexpected guard before {call_name}"

        assert len(guard.body) == 1
        check_statement = guard.body[0]

        assert isinstance(check_statement, ast.Expr)
        assert isinstance(check_statement.value, ast.Call)
        assert isinstance(check_statement.value.func, ast.Name)
        assert check_statement.value.func.id == (
            "cancellation_check"
        )

        checked += 1

    assert checked > 0


@pytest.mark.parametrize("name", SERVICES)
def test_cancellation_stops_service_before_s3(
    name, monkeypatch
):
    monkeypatch.setenv("S3_BUCKET", "rentready-test-bucket")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("APP_ENV", "test")

    services = importlib.import_module("app.services")

    class Stopped(Exception):
        pass

    callback = Mock(side_effect=Stopped())
    head_object = Mock(
        side_effect=AssertionError(
            "S3 operation should not begin after cancellation"
        )
    )

    monkeypatch.setattr(
        services.s3,
        "head_object",
        head_object,
    )

    with pytest.raises(Stopped):
        getattr(services, name)(
            inspection_id="inspection-123",
            source_key="test/input.mp4",
            parameters={},
            agent_context={},
            job_id="agent-job-123",
            require_cool=False,
            cancellation_check=callback,
        )

    callback.assert_called_once()
    head_object.assert_not_called()
