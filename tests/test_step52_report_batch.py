"""Step 52: batch frame URLs without repeated manifest reads."""

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_SESSION_TOKEN", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "rentready-test-bucket")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import inspections as routes


app = FastAPI()
app.include_router(routes.router)
client = TestClient(app)


def test_120_frame_urls_use_one_manifest_read(monkeypatch):
    reads = []
    calls = []

    def load(inspection_id):
        reads.append(inspection_id)
        return {
            "keyframes": [
                {
                    "index": index,
                    "s3_key": f"frames/frame-{index}.jpg",
                }
                for index in range(120)
            ]
        }

    class FakeS3:
        def generate_presigned_url(
            self, operation, *, Params, ExpiresIn
        ):
            calls.append((operation, Params, ExpiresIn))
            return "https://example.invalid/" + Params["Key"]

    monkeypatch.setattr(
        routes, "_require_inspection",
        lambda inspection_id: {
            "inspection_id": inspection_id,
            "status": "COMPLETE",
        },
    )
    monkeypatch.setattr(routes, "load_manifest", load)
    monkeypatch.setattr(routes, "s3", FakeS3())

    response = client.get("/inspections/example/frames/urls")

    assert response.status_code == 200

    body = response.json()

    assert body["inspection_id"] == "example"
    assert len(body["frames"]) == 120
    assert len(reads) == 1
    assert len(calls) == 120

    assert body["frames"][0]["index"] == 0
    assert body["frames"][-1]["index"] == 119
    assert calls[0][0] == "get_object"
    assert calls[0][1]["Bucket"] == routes.settings.s3_bucket


def test_missing_manifest_returns_409(monkeypatch):
    monkeypatch.setattr(
        routes, "_require_inspection",
        lambda inspection_id: {"inspection_id": inspection_id},
    )

    def missing(_inspection_id):
        raise FileNotFoundError("Manifest is not available yet")

    monkeypatch.setattr(routes, "load_manifest", missing)

    response = client.get("/inspections/example/frames/urls")

    assert response.status_code == 409
    assert "Manifest is not available" in response.json()["detail"]
