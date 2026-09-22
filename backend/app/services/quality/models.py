from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class QualityIssueCode(StrEnum):
    QUALITY_CHECK_FAILED = "quality_check_failed"
    QUALITY_REPORT_STALE = "quality_report_stale"


class DeliveryVerificationStatus(StrEnum):
    FAILED = "failed"
    MANUAL_ACCEPTANCE_REQUIRED = "manual_acceptance_required"
    MANUALLY_ACCEPTED = "manually_accepted"


class DeliveryQualityIssue(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    severity: Literal["error", "warning", "info"]
    message: str
    scene_id: str | None = None
    visual_beat_id: str | None = None
    subtitle_id: str | None = None
    subtitle_cue_index: int | None = None
    subtitle_start_ms: int | None = None
    suggestion: str | None = None
    file_path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DeliveryQualitySummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    scene_count: int = 0
    assignment_count: int = 0
    shot_assignment_count: int = 0
    subtitle_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    audio_duration_seconds: float | None = None
    prproj_path: str | None = None
    audio_path: str | None = None
    srt_path: str | None = None


class ManualAcceptance(BaseModel):
    editor: str = Field(min_length=1)
    editor_version: str = ""
    checked_at: str
    checked_by: str | None = None
    audio_ok: bool
    subtitles_ok: bool
    media_links_ok: bool
    notes: str = ""


class DeliveryQualityReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1] = 1
    report_id: str
    project_id: str
    created_at: str
    passed: bool
    delivery_verified: bool
    premiere_conversion_verified: bool
    verification_status: DeliveryVerificationStatus
    manual_acceptance_required: bool = True
    manual_acceptance: ManualAcceptance | None = None
    stale: bool = False
    summary: DeliveryQualitySummary
    issues: list[DeliveryQualityIssue]
    file_signatures: dict[str, Any]
    project_signature: str | None


def migrate_quality_report(payload: dict, *, project_id: str) -> dict:
    """Upgrade legacy unversioned reports without rewriting them during a read."""
    migrated = dict(payload)
    migrated.setdefault("schema_version", 1)
    migrated.setdefault("report_id", f"legacy:{project_id}")
    migrated.setdefault("project_id", project_id)
    migrated.setdefault("created_at", "")
    migrated.setdefault("manual_acceptance_required", True)
    migrated.setdefault("manual_acceptance", None)
    migrated.setdefault(
        "verification_status",
        "manual_acceptance_required" if migrated.get("delivery_verified") else "failed",
    )
    migrated.setdefault("premiere_conversion_verified", False)
    migrated.setdefault("file_signatures", {})
    migrated.setdefault("project_signature", None)
    return migrated
