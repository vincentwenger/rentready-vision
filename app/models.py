from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field


class InspectionStatus(StrEnum):
    CREATED = "CREATED"
    UPLOAD_PENDING = "UPLOAD_PENDING"
    UPLOADED = "UPLOADED"
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
    error: str | None = None
    created_at: str
    updated_at: str


class Keyframe(BaseModel):
    index: int
    timestamp_seconds: float
    s3_key: str
    sharpness: float
    brightness: float
    scene_index: int


class FramesResponse(BaseModel):
    inspection_id: str
    keyframes: list[Keyframe]
    scenes: list[dict[str, Any]]
