from enum import StrEnum


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProjectStatus(StrEnum):
    CREATED = "created"
    SCRIPT_IMPORTED = "script_imported"
    SEGMENTED = "segmented"
    NARRATION_IN_PROGRESS = "narration_in_progress"
    NARRATION_READY = "narration_ready"
    VIDEO_IN_PROGRESS = "video_in_progress"
    REVIEW_REQUIRED = "review_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResourceClass(StrEnum):
    CPU = "cpu"
    GPU = "gpu"
    NETWORK = "network"
    FFMPEG = "ffmpeg"
    API = "api"
