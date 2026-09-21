from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field

from .vision.issue_taxonomy import TAXONOMY_VERSION


class InspectionStatus(StrEnum):
    CREATED = "CREATED"
    UPLOAD_PENDING = "UPLOAD_PENDING"
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    RETRY_PENDING = "RETRY_PENDING"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class InspectionPurpose(StrEnum):
    RENTAL_PREP = "rental_prep"


class CreateInspectionRequest(BaseModel):
    property_label: str | None = Field(default=None, max_length=200)
    purpose: InspectionPurpose = InspectionPurpose.RENTAL_PREP


class CreateInspectionResponse(BaseModel):
    inspection_id: str
    status: InspectionStatus


class CreateUploadUrlRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str


class UploadUrlResponse(BaseModel):
    inspection_id: str
    upload_url: str
    method: str = "PUT"
    s3_key: str
    expires_in_seconds: int
    required_headers: dict[str, str]


class UploadCompleteRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str


class InspectionResponse(BaseModel):
    inspection_id: str
    status: InspectionStatus
    purpose: str
    property_label: str | None = None
    original_s3_key: str | None = None
    manifest_s3_key: str | None = None
    video: dict[str, Any] | None = None
    processing: dict[str, Any] | None = None
    active_job_id: str | None = None
    processing_backend: str | None = None
    processing_telemetry: dict[str, Any] | None = None
    processing_receive_count: int | None = None
    last_processing_event: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class Keyframe(BaseModel):
    index: int
    frame_number: int | None = None
    timestamp_seconds: float
    s3_key: str
    sharpness: float
    tile_median_sharpness: float | None = None
    sharp_tiles_percent: float | None = None
    motion_blur_suspected: bool | None = None
    blur_classification: str | None = None
    brightness: float
    brightness_classification: str | None = None
    dark_pixels_percent: float | None = None
    bright_pixels_percent: float | None = None
    motion_percent_per_second: float | None = None
    motion_pixels_per_second: float | None = None
    motion_classification: str | None = None
    tracked_features: int | None = None
    evidence_quality_score: float | None = None
    scene_index: int
    selection_reason: str | None = None
    keyframe_selection_score: float | None = None
    keyframe_selection_components: dict[str, float] | None = None
    keyframe_selection_rank: int | None = None


class FramesResponse(BaseModel):
    inspection_id: str
    video: dict[str, Any]
    processing: dict[str, Any]
    keyframes: list[Keyframe]
    scenes: list[dict[str, Any]]
    frame_assessments: list[dict[str, Any]] = Field(default_factory=list)


class IssuesResponse(BaseModel):
    inspection_id: str
    status: str = "NOT_RUN"
    taxonomy_version: str = TAXONOMY_VERSION
    structured_finding_version: str | None = None
    detector: dict[str, Any] | None = None
    taxonomy: dict[str, Any] | None = None
    rooms: list[str] = Field(default_factory=list)
    candidate_findings: list[dict[str, Any]] = Field(default_factory=list)
    raw_candidate_findings: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    raw_issues: list[dict[str, Any]] = Field(default_factory=list)
    severity_classification: dict[str, Any] | None = None
    consolidation: dict[str, Any] | None = None
    confidence_scale: dict[str, Any] | None = None
    responsible_language: dict[str, Any] | None = None
    polished_report: dict[str, Any] | None = None
    report_s3_key: str | None = None
    note: str = (
        "Step 27 describes visible conditions without diagnosing hidden causes or determining "
        "electrical safety or structural significance. Qualified human inspection remains essential."
    )


class AgenticRunRequest(BaseModel):
    seconds_before: float | None = Field(default=None, ge=0, le=30)
    seconds_after: float | None = Field(default=None, ge=0, le=30)
    sample_fps: float | None = Field(default=None, gt=0, le=30)


class CropRegionRunRequest(BaseModel):
    padding: float = Field(default=0.15, ge=0, le=2.0)


class EnhanceRegionRunRequest(BaseModel):
    contrast: float = Field(default=1.25, ge=0.5, le=3.0)
    brightness_normalization: bool = True
    sharpening: float = Field(default=0.8, ge=0.0, le=2.0)


class OtherAngleRunRequest(BaseModel):
    search_seconds_before: float = Field(default=4.0, ge=0, le=30)
    search_seconds_after: float = Field(default=4.0, ge=0, le=30)
    sample_every_seconds: float = Field(default=0.5, ge=0.1, le=5.0)
    max_results: int = Field(default=3, ge=2, le=5)
    min_viewpoint_change: float = Field(default=0.06, ge=0.0, le=1.0)


class DecisionPolicyRunRequest(BaseModel):
    candidate_issue_id: str | None = Field(default=None, max_length=80)
    seconds_before: float | None = Field(default=None, ge=0, le=30)
    seconds_after: float | None = Field(default=None, ge=0, le=30)
    sample_fps: float | None = Field(default=None, gt=0, le=30)
    crop_padding: float | None = Field(default=None, ge=0, le=2.0)


class AgenticRunResponse(BaseModel):
    inspection_id: str
    status: str
    decision: str
    job_id: str | None = None
    backend: str | None = None
    candidate: dict[str, Any] | None = None
    tool_call: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    candidate_decisions: list[dict[str, Any]] = Field(default_factory=list)
    note: str | None = None
