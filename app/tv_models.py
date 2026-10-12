"""Read-only public response shapes for the RentReady Vision TV client.

These models deliberately exclude internal report structure,
DynamoDB keys, S3 keys, worker state and privileged credentials.

Authentication and inspection-level authorization are mandatory
before these models are served by an API endpoint.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TvSeverity = Literal["high", "medium", "low", "unknown"]


class TvResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TvInspectionCard(TvResponse):
    id: str
    property_name: str
    status: Literal["COMPLETE"]
    finding_count: int = Field(ge=0)


class TvInspectionListResponse(TvResponse):
    inspections: list[TvInspectionCard]


class TvSeverityCounts(TvResponse):
    high: int = Field(ge=0)
    medium: int = Field(ge=0)
    low: int = Field(ge=0)
    unknown: int = Field(default=0, ge=0)


class TvInspectionOverview(TvResponse):
    id: str
    property_name: str
    status: Literal["COMPLETE"]
    finding_count: int = Field(ge=0)
    severity_counts: TvSeverityCounts


class TvRoomSummary(TvResponse):
    id: str
    name: str
    finding_count: int = Field(ge=0)
    finding_ids: list[str]


class TvRoomsResponse(TvResponse):
    inspection_id: str
    rooms: list[TvRoomSummary]


class TvFindingSummary(TvResponse):
    id: str
    inspection_id: str
    room: str
    title: str
    severity: TvSeverity
    confidence: float | None = Field(default=None, ge=0, le=1)
    timestamp_seconds: float | None = Field(default=None, ge=0)
    description: str | None = None


class TvFindingsResponse(TvResponse):
    inspection_id: str
    findings: list[TvFindingSummary]


class TvFindingDetail(TvFindingSummary):
    recommended_action: str | None = None
    evidence_image_url: str | None = None
    evidence_video_url: str | None = None


class TvBriefingResponse(TvResponse):
    inspection_id: str
    headline: str
    priority_finding_id: str | None = None
    priority_room: str | None = None
    recommended_action: str | None = None
    medium_count: int = Field(ge=0)
    disclaimer: str
